*Ce projet a été réalisé dans le cadre du cursus 42 par slidriss, thmaille.*

# Agent Smith

## Description

Agent Smith est un framework d'**agent de code**. Il résout des tâches de programmation tout seul :
le LLM écrit du code Python, le code s'exécute dans une **sandbox** sécurisée, la
sortie est renvoyée au LLM, et le cycle recommence jusqu'à ce que la tâche soit résolue.

Il tourne sur deux benchmarks :

| Benchmark | Tâche | Ce que l'agent soumet |
|---|---|---|
| **MBPP** | petits problèmes algorithmiques en Python | le code source de la fonction |
| **SWE-bench Verified** | de vrais bugs dans de vrais dépôts open source (dans Docker) | un patch git |

Fonctionnalités principales :

- la boucle de l'agent est notre propre boucle **Thought → Code → Observation** (aucune bibliothèque d'agent) ;
- les outils sont appelés **depuis du code Python** (`result = read_file(...)`), pas par du tool calling JSON ;
- la sandbox restreint les imports, les builtins, les fichiers, le réseau, les processus, le temps et la mémoire ;
- les outils sont servis par nos propres **serveurs MCP** (stdio ou streamable HTTP) ;
- le client fonctionne avec n'importe quel fournisseur LLM compatible OpenAI, et gère plusieurs clés API avec rotation ;
- chaque étape est entièrement journalisée dans `solution.json` (tokens, latence, retries, sortie brute du LLM, entrée/sortie de la sandbox).

## Instructions

### Prérequis

- Python 3.10 et [uv](https://docs.astral.sh/uv/)
- Docker, uniquement pour SWE-bench (les images sont en `linux/amd64`)

### Installation

```bash
uv sync
cp .env.example .env      # puis mettre ses clés API dans .env
```

Les clés API sont lues **uniquement** depuis les variables d'environnement ou depuis `.env` :
`<PROVIDER>_API_KEY`, puis `<PROVIDER>_API_KEY_2`, `_3`, … pour la rotation.
Le nom du fournisseur est déduit de l'URL (`https://api.groq.com/openai/v1` → `GROQ`).

### Sandbox interactive

```bash
uv run sandbox                                                          # config par défaut
uv run sandbox sandbox_template.json                                    # config personnalisée
uv run sandbox --mcp-stdio "python mcp_tools_mbpp.py" sandbox_template.json
uv run sandbox --mcp-server http://127.0.0.1:8000/mcp                   # serveur HTTP
uv run sandbox --mcp-stdio "python mcp_tools_swebench.py" sandbox_template.json
```

Pour lancer un serveur MCP en HTTP : `python mcp_tools_mbpp.py --http [--port 8000]`.
Taper `exit` ou faire Ctrl+D pour quitter le REPL.

### Agent MBPP

```bash
uv run python -m agent_mbpp --task-file ../cache/mbpp_task.json \
    --output ../cache/mbpp_solution.json \
    --model-name "model/name" --provider-url "https://provider.api/v1" \
    [--max-iterations 10]
```

### Agent SWE-bench

```bash
uv run python -m agent_swebench --task-file ../cache/swebench_task.json \
    --output ../cache/swebench_solution.json \
    --model-name "model/name" --provider-url "https://provider.api/v1"
```

### Tests

```bash
uv run pytest tests/ -v
```

## Architecture du système

```
                      ┌───────────────────────────── hôte ─────────────────────────────┐
 task.json ──► agent_mbpp / agent_swebench (CLI)
                      │
                      ▼
              ┌───────────────┐   messages    ┌──────────────┐
              │ Boucle agent  │ ────────────► │  LLMClient   │ ──► API compatible OpenAI
              │  (loop.py)    │ ◄──────────── │ + KeyRing    │     (Groq, OpenRouter, Gemini…)
              └───────┬───────┘  texte brut   └──────────────┘
                      │ extract_code()  (python / XML invoke / Hermes / ReAct → Python)
                      ▼
              ┌───────────────────────────────────────────┐
              │ Sandbox (processus parent)                │
              │   ├─ McpClient ──stdio / HTTP──► serveur MCP (mcp_tools_*.py)
              │   │                                 │  SWE-bench : docker exec ──► conteneur /testbed
              │   └─ Pipe ◄──► processus enfant (spawn)
              │          exec() avec builtins sûrs, garde d'import,
              │          vérification AST, audit hook, RLIMIT_AS
              └───────────────────────────────────────────┘
                      │ ExecResult (output, final_answer, notices, timed_out)
                      ▼
               Observation ──► tour LLM suivant … ──► solution.json
```

```
smith_core/
├── models.py            Modèles Pydantic : SandboxConfig, entrées des tâches, StepMetrics, SolutionOutput, ExecResult
├── llm/
│   ├── clients.py       LLMClient : appel chat compatible OpenAI, retries, suivi de l'usage
│   └── keys.py          KeyRing : plusieurs clés par fournisseur + rotation
├── agent/
│   ├── loop.py          run_agent() : la boucle Thought → Code → Observation et les budgets
│   ├── extract.py       extract_code() : essaie chaque format, construit les notices
│   ├── formats.py       un parseur par format de sortie
│   ├── helpers.py       convertit un appel d'outil en ligne Python
│   └── prompts.py       insère le manuel de la sandbox dans un template de prompt
└── sandbox/
    ├── executor.py      Sandbox : processus enfant, timeout, crash, troncature, dispatch MCP
    ├── security.py      garde d'import, builtins sûrs, vérification AST, open sécurisé, audit hook
    ├── mcp_client.py    McpClient : stdio + streamable HTTP, tools / resources / prompts
    ├── manual.py        construit le manuel des outils à partir des schémas MCP
    └── cli.py           REPL `uv run sandbox`
agent_mbpp/              CLI MBPP, prompt, solution de repli
agent_swebench/          CLI SWE-bench, cycle de vie Docker (docker.py)
mcp_tools_mbpp.py        Serveur MCP : run_tests
mcp_tools_swebench.py    Serveur MCP : les 9 outils SWE-bench obligatoires
sandbox_template.json    configuration de la sandbox
tests/                   suites pytest (sécurité sandbox, client MCP, outils, extraction…)
```

Les couches sont indépendantes. Les outils marchent sans l'agent, la sandbox
marche sans le LLM (REPL), et la boucle a seulement besoin d'un objet qui a une
méthode `execute(code)`.

## Boucle de l'agent

`run_agent()` dans `smith_core/agent/loop.py` :

```
messages = [prompt système (template + manuel sandbox), prompt utilisateur (tâche)]
pour step de 1 à max_iterations :
    si pas budget_left() : stop                  # temps, tokens d'entrée et de sortie
    text  = llm.chat(messages, stop=["<end_code>"])
    code, notice = extract_code(text)
    si code est None : observation = notice      # "No valid code block found…"
    sinon :            result = sandbox.execute(code)
                       observation = notices + sortie
    enregistrer StepMetrics(tokens, latence, retries, llm_output, sandbox_input, sandbox_output)
    si final_answer a été appelé : stop
    messages += [assistant : text, user : "Observation:\n" + observation]
solution = réponse finale, ou fallback(steps) si l'agent n'a jamais appelé final_answer
```

- **Thought → Code → Observation** : le prompt demande `Thought:`, puis un
  bloc ```` ```python ```` terminé par `<end_code>`.
- **Séquence d'arrêt** : `<end_code>` arrête la génération, donc le modèle ne peut pas
  inventer une fausse `Observation:`. S'il en écrit quand même une, tout ce qui suit
  est ignoré et le modèle reçoit une note à ce sujet.
- **Plusieurs formats de sortie** : `extract_code` essaie d'abord les blocs Python, puis
  le XML `<invoke>` façon Anthropic, le JSON Hermes `<tool_call>` et le ReAct
  `Action:` / `Action Input:`. Les formats non-Python sont convertis en appel Python
  (`result = read_file(filepath='...')` + `print(result)`), donc la
  sandbox ne reçoit jamais que du Python.
- **Retour explicite** : le LLM est prévenu quand il n'y a pas de bloc de code, quand
  un bloc n'était pas fermé mais a quand même été exécuté, quand plusieurs blocs ont été
  regroupés, quand des blocs non-Python ont été ignorés, quand le code a dépassé le temps,
  et quand la sortie a été tronquée.
- **Budgets** : avant chaque appel, `budget_left()` vérifie le temps écoulé (plus la
  requête la plus lente jusque-là) et les tokens de sortie restants. Il estime aussi la taille
  de la prochaine entrée (entrée précédente + sortie précédente + une marge). Le `max_tokens`
  de chaque appel est plafonné par ce qui reste. Les limites MBPP sont 10 itérations,
  6 000 tokens d'entrée, 1 500 tokens de sortie et 120 s. Les limites SWE-bench sont 30, 300 000, 10 000 et 900 s.
- **Suivi de l'usage** : chaque étape enregistre ses tokens d'entrée/sortie, le temps de requête,
  l'URL de l'API, le nom du modèle et le nombre de retries. Les totaux vont dans `SolutionOutput`.
- **Robustesse** : la CLI écrit toujours un `solution.json` valide, même
  quand le fichier de tâche, le LLM ou la sandbox échoue (champ `error`).

Client LLM (`smith_core/llm/clients.py`) : un seul client compatible OpenAI, donc changer
de fournisseur revient juste à changer `--provider-url`. Sur une erreur 429, 5xx ou une
erreur de connexion, il passe à la clé suivante du `KeyRing` et réessaie
avec un backoff exponentiel (jusqu'à 3 retries, comptés dans `StepMetrics.retries`).

## Conception de la sandbox

La sandbox (`smith_core/sandbox/`) est la frontière de sécurité entre le
code généré par le LLM et la machine. Elle utilise **uniquement la bibliothèque standard**.

### Isolation : un processus enfant

Le code s'exécute dans un **processus enfant séparé**, lancé avec
`multiprocessing` en mode `spawn`. Le parent et l'enfant communiquent par un `Pipe`.

| Pourquoi un processus enfant | |
|---|---|
| Timeout | un `while True` bloqué ne peut pas être arrêté depuis le même processus. Un enfant peut être **tué** |
| Crash | un segfault ou un manque de mémoire tue l'enfant, pas l'agent |
| Mémoire | `RLIMIT_AS` s'applique seulement à l'enfant |
| État persistant | l'enfant garde un seul namespace, donc les variables survivent d'une étape à l'autre |

Les messages de l'enfant sont : `stdout` (envoyé en direct par `_PipeStdout`), `tool` (demande
d'appel MCP) et `done` (fin d'exécution, avec `final`, `error` et
éventuellement `control`).

### Couches de sécurité

| Menace | Protection | Où |
|---|---|---|
| `import os` / `subprocess` / `socket` | **liste blanche d'imports** : `__import__` est remplacé dans les builtins de la sandbox. `pkg.*` autorise les sous-modules, les imports relatifs sont refusés, `from pkg import sous_module` est aussi vérifié | `make_guarded_import` |
| `eval`, `exec`, `compile`, `input`, `breakpoint`, `globals`, `vars`… | retirés d'une **copie** des builtins (les vrais ne sont pas touchés) | `build_safe_builtins` |
| Évasions via `().__class__.__subclasses__()`, `f.__globals__`… | **vérification AST** avant `exec` : tout attribut ou nom dunder est refusé (sauf `__name__`, `__import__`). `getattr(x, "__class__")` est bloqué par `safe_getattr` | `check_ast`, `safe_getattr` |
| Lire/écrire des fichiers hors de l'espace de travail | `open` n'accepte que les chemins dans `allowed_directories` (les deux côtés résolus avec `realpath`, donc `..` et les liens symboliques ne permettent pas de sortir) | `make_safe_open` |
| Accès indirect (un module autorisé qui utilise `os` en interne, ex. `random._os.system`) | **audit hook** (`sys.addaudithook`, PEP 578), installé dans l'enfant : il bloque tout `open` hors des dossiers autorisés (la lecture seule est permise dans l'installation Python), et tout événement `socket.*`, `subprocess.*`, `os.system`, `os.exec*`, `os.spawn*`, `os.fork`, `os.kill`, `ctypes.*` | `make_audit_hook` |
| Réseau | la garde d'import (pas de `socket`/`urllib`), plus l'audit hook sur les événements `socket.*` | |
| Boucle infinie | le parent attend avec `conn.poll(remaining)`. Après `max_execution_time_seconds`, il tue l'enfant et en relance un neuf. La sortie partielle est renvoyée avec une notice. Le chrono est **mis en pause pendant les appels d'outils MCP** (les outils tournent hors de la sandbox) | `Sandbox.execute`, `_on_timeout` |
| Bombe mémoire | `resource.setrlimit(RLIMIT_AS, max_memory_mb)` dans l'enfant. Une `MemoryError` est signalée clairement. Si l'enfant meurt, il est relancé (`_on_crash`). Remarque : `RLIMIT_AS` est ignoré par macOS mais appliqué sous Linux | `_limit_memory` |
| Sorties énormes | la sortie garde son début et sa fin (10 000 caractères max), et le LLM reçoit une notice avec le nombre de caractères omis | `_truncate` |

`final_answer(x)` lève une exception privée `FinalAnswer`. Elle hérite de
`BaseException`, donc un `try/except Exception` dans le code du LLM ne peut pas
l'attraper. L'enfant envoie la valeur au parent, et la boucle s'arrête.

`SystemExit` et `KeyboardInterrupt` ne sont **pas avalées**. L'enfant les envoie
sous forme de message `control`, et le parent les relève, donc elles atteignent la
boucle de l'agent.

### Configuration

Les limites viennent d'un `SandboxConfig` Pydantic, chargé depuis du JSON
(`sandbox_template.json`) :

```json
{
  "authorized_imports": ["math", "math.*", "collections", "collections.*", "itertools", "re", "..."],
  "allowed_directories": ["/testbed", "/tmp/agent"],
  "max_execution_time_seconds": 30,
  "max_memory_mb": 512
}
```

### Intégration MCP

- `McpClient` fait tourner la session MCP asynchrone dans un thread en arrière-plan. La
  sandbox l'appelle de façon synchrone.
- **Transports** : `McpClient.from_stdio(command)` lance le serveur comme
  sous-processus. `McpClient.from_http(url)` utilise le streamable HTTP. Les deux partagent le
  même code ; seule la fabrique de transport change.
- **Découverte dynamique** : au démarrage, la sandbox liste les outils,
  ressources et prompts du serveur. Pour chaque outil, elle construit un wrapper Python dans le
  namespace de l'enfant. Le wrapper envoie `{"type": "tool", ...}` par le pipe,
  le parent appelle l'outil MCP, et le résultat revient comme valeur de retour.
  Les arguments positionnels sont associés aux noms de paramètres du schéma.
  Si le serveur a des ressources ou des prompts, `read_resource(uri)` et
  `get_prompt(name, arguments)` sont aussi ajoutés.
- `final_answer` n'est **pas** un outil MCP. Il est toujours présent, quel que soit le serveur.
- **Manuel** : `Sandbox.manual()` construit la documentation des outils à partir des
  schémas JSON du serveur : signature avec types Python et valeurs par défaut, première ligne
  de la description, la ligne `Returns:`, puis les ressources, les prompts,
  les imports autorisés, les dossiers et les limites. Connecter un autre
  serveur change le manuel automatiquement. Ce manuel est inséré dans
  le prompt système (`{manual}`).

## Implémentation des outils

### Serveur MBPP (`mcp_tools_mbpp.py`)

- `run_tests(code, test_list)` exécute la solution et les asserts dans un **nouveau
  processus Python isolé** (`python -I`, dossier de travail temporaire,
  timeout de 10 s). Il renvoie `{"success": bool, "output": str}` en JSON, avec une
  ligne `PASS:` / `FAIL:` par assert.
- Le serveur expose aussi une ressource (`mbpp://guide`) et un prompt (`solve_task`).

### Serveur SWE-bench (`mcp_tools_swebench.py`)

La racine du dépôt vient de la variable d'environnement **`TESTBED_PATH`** (par défaut
`/testbed`). Le serveur a deux modes, choisis par une seule variable :

| Mode | Quand | Comment une commande s'exécute |
|---|---|---|
| local | tests des outils par la moulinette, notre pytest | `bash -c <cmd>` avec `cwd` |
| Docker | `SWEBENCH_CONTAINER=<nom>` est défini | `docker exec -i -w <cwd> <nom> bash -c <cmd>` |

On utilise donc l'option (b) du sujet : la sandbox tourne sur l'hôte, et les
outils MCP font le pont vers le conteneur. Tous les outils passent par trois helpers :

- `_sh(command, workdir, timeout, stdin)` : lance une commande et renvoie `(code, stdout, stderr)`. Il ne lève jamais d'exception : timeout → code 124, commande introuvable → code 1 avec un message ;
- `_read` / `_write` : lisent et écrivent les fichiers avec Python en local, ou avec `cat` / `cat >` (via stdin) dans Docker ;
- `_abs(path)` : les chemins relatifs sont résolus depuis la racine du dépôt et normalisés.

Toute valeur venant du LLM est protégée avec `shlex.quote`. Les sorties longues sont
coupées à 10 000 caractères, avec un message clair.

| Outil | Implémentation | Sortie |
|---|---|---|
| `read_file(filepath, start_line=1, end_line=None)` | lit le fichier, valide l'intervalle | `n: ligne` (comme `cat -n`), erreurs pour un fichier vide, une ligne hors limites ou `end < start` |
| `edit_file(filepath, old_str, new_str)` | `old_str` doit apparaître **exactement une fois**. Pour les fichiers `.py`, le nouveau contenu est vérifié avec `compile()` **avant** l'écriture : en cas d'erreur de syntaxe, le fichier n'est pas modifié et le LLM est prévenu | `Edited <file> at line N.` |
| `list_files(directory=".", pattern="*")` | `find -type f -name <pattern>`, `.git` exclu, trié | chemins absolus, ou `No files found.` |
| `search_code(pattern, file_pattern="*.py")` | `grep -rnIE` (regex étendue, fichiers binaires ignorés, `.git` exclu). Le code de sortie 1 signifie aucun résultat, pas une erreur | `/chemin/abs.py:<ligne> <contenu>` |
| `search_function_or_class_definition_in_code(name)` | vérifie que `name` est un identifiant valide, puis cherche `^\s*(async\s+)?(def\|class)\s+NAME\b` | même format que `search_code` |
| `find_references(name, filepath, line)` | vérifie que `name` est bien à `filepath:line`, puis `grep -rnIwF` (mot entier, texte littéral) | même format que `search_code` |
| `run_command(command, workdir=".")` | `bash -c` dans le workdir, timeout de 120 s | `exit_code`, `stdout`, `stderr` |
| `run_tests()` | lance le script d'évaluation (`EVAL_SCRIPT_PATH`, par défaut `/eval.sh`), timeout de 600 s. La **fin** de la sortie est conservée, car le résumé des tests s'y trouve | `exit_code`, `stdout`, `stderr` |
| `get_patch()` | `git -c core.fileMode=false diff` dans le dépôt (jamais tronqué) | diff unifié |

Les outils sont testés indépendamment dans `tests/test_tools_swebench.py`. La fixture
construit un petit dépôt git dans un dossier temporaire et fait pointer `TESTBED_PATH`
dessus, exactement comme le fait la moulinette.

## Résultats et analyse du benchmark

Le rapport complet est dans [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md). Les fichiers
`solution.json` correspondants sont dans `benchmark/`.

> TODO : tableau récapitulatif (5 modèles × 3 tâches SWE-bench), le modèle choisi et pourquoi.

## Ressources

- [Model Context Protocol – spécification](https://modelcontextprotocol.io/) et le [SDK Python MCP](https://github.com/modelcontextprotocol/python-sdk)
- [smolagents – CodeAgent](https://huggingface.co/docs/smolagents/conceptual_guides/intro_agents) (idée du tool calling par le code ; pas utilisé comme bibliothèque)
- *Executable Code Actions Elicit Better LLM Agents* (CodeAct), Wang et al., 2024
- *ReAct: Synergizing Reasoning and Acting in Language Models*, Yao et al., 2022
- [SWE-bench](https://www.swebench.com/) et *SWE-agent: Agent-Computer Interfaces*, Yang et al., 2024
- *Program Synthesis with Large Language Models* (MBPP), Austin et al., 2021
- Docs Python : [`multiprocessing`](https://docs.python.org/3/library/multiprocessing.html), [`sys.addaudithook` / PEP 578](https://peps.python.org/pep-0578/), [`ast`](https://docs.python.org/3/library/ast.html), [`resource`](https://docs.python.org/3/library/resource.html)
- [Client Python OpenAI](https://github.com/openai/openai-python) (utilisé avec les fournisseurs compatibles OpenAI)

### Utilisation de l'IA

- **Explications et discussions de conception** : nous avons utilisé Claude pour expliquer des concepts
  (audit hooks, `spawn`, transports MCP, images Docker de SWE-bench) et pour discuter des
  compromis entre les options. Nous avons fait les choix de conception ensemble, en équipe.
- **Code guidé** : pour la sandbox et les outils, l'IA a surtout donné des indices et
  du code à trous. Nous avons écrit et corrigé le code nous-mêmes, puis
  nous l'avons relu ligne par ligne.
- **Tests** : l'IA a aidé à rédiger certains cas pytest (par exemple la fixture git de
  `tests/test_tools_swebench.py`). Nous les avons relus et adaptés.
- **Documentation** : ce README a été rédigé avec l'IA à partir de notre code, puis
  relu et corrigé par nous.
- Le code de l'agent lui-même résout les tâches avec les fournisseurs LLM listés dans le
  rapport de benchmark. Aucune solution ne vient de pull requests, d'issues ou d'autres sources externes.
