def build_system_prompt(template: str, manual: str) -> str:
    """create a prompt to MBPP and SWE"""
    return template.replace("{manual}", manual)
