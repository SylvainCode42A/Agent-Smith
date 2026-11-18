
# Commande de lancement:

# colima stop
# colima delete
# colima start --vm-type vz --vz-rosetta --cpu 4 --memory 8 --disk 100
# docker run --rm --platform linux/amd64 alpine uname -m

# Prochaine étape : l’exploration à la main (étape 0).

# Depuis le dossier moulinette, dump d’une tâche SWE-bench.

# Pour commencer par la plus simple conseillée par le sujet,
# regarde :
# ./quickstart.sh --help ou uv run moulinette_eval dump --help
# -> sympy__sympy-14711.

# Ouvre le JSON obtenu et repère docker_image et eval_script.
# docker pull --platform linux/amd64 <image> : c’est le gros téléchargement.

# Puis le cycle à la main :
# docker run -d --platform linux/amd64 --name test_smith <image> sleep infinity
# docker exec test_smith ls /testbed
# docker exec test_smith git -C /testbed status
# docker rm -f test_smith

# ---------------------


# Ce qu’on a fait

# 1. colima stop : arrêter Colima.
# Colima est le programme qui fait tourner Docker sur ton Mac,
# à l’intérieur d’une petite machine virtuelle.
# On l’a arrêté pour pouvoir le reconfigurer.

# 2. colima delete : supprimer la machine virtuelle de Colima.
# Sa configuration ne pouvait pas faire tourner efficacement des
# conteneurs Intel, et ce réglage ne se change pas sur une machine existante:
# il fallait la recréer. Ça a effacé les images Docker déjà téléchargées,
# mais il n’y avait rien d’important.

# 3. colima start --vm-type vz --vz-rosetta --cpu 4 --memory 8 --disk 100 :
# recréer Colima avec les bons réglages.

# --vm-type vz : utiliser le système de virtualisation d’Apple, plus rapide ;
# --vz-rosetta : utiliser Rosetta, le traducteur d’Apple, pour exécuter les
# programmes Intel sur ta puce Apple. C’est le réglage clé : sans lui, les
# conteneurs SWE-bench seraient émulés et très lents;
# --cpu 4 --memory 8 --disk 100 : 4 cœurs, 8 Go de mémoire et 100 Go de disque,
# parce que les images SWE-bench sont lourdes.

# Avant ça, on avait vérifié que Rosetta était installé
# (arch -x86_64 uname -m).

# 4. docker run --rm --platform linux/amd64 alpine uname -m :
# le test de vérification.
# On a lancé un petit conteneur Linux en version Intel
# (--platform linux/amd64) et demandé « quel est ton processeur ? ».
# Il a répondu x86_64 : la preuve que ton Mac fait maintenant tourner
# des conteneurs Intel. --rm supprime le conteneur dès qu’il a fini.

# 5. moulinette_eval dump swebench --task_id sympy__sympy-14711 :
# récupérer une vraie tâche.
# La moulinette a écrit un fichier JSON avec tout ce que recevra votre agent:
# le bug à corriger (problem_statement), le nom de l’image Docker à utiliser
# (docker_image), et le script qui vérifiera la correction (eval_script).

# 6. La lecture de l’eval_script : comprendre comment la correction sera jugée.
# Le script active l’environnement du projet, ajoute un nouveau test
# (A.x + 0 == A.x), lance les tests, puis remet le fichier de test d’origine.
# Si ce nouveau test passe, le bug est corrigé.

# Où on en est

# Ton Mac est prêt, et tu as une vraie tâche en main. Il reste à télécharger
# l’image de cette tâche (docker pull):
# docker pull --platform linux/amd64 swebench/sweb.eval.x86_64.sympy_1776_sympy-14711:latest

# puis à explorer le conteneur à la main.
# Ça te montrera concrètement ce que ton code devra automatiser :
# démarrer le conteneur (start_container),
# y copier l’eval_script (copy_eval_script),
# puis le supprimer (remove_container).
