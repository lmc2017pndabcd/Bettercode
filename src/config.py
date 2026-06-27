from rich.console import Console
import os
import subprocess
import shlex
import sys
c = Console()

def main():
    color = "[bold green]"
    color_end = "[/bold green]"

    config_path = os.path.expanduser("~/.codemax")
    
    if not os.path.exists(config_path):
        open(config_path, "w").close()

    url = c.input(f"{color}Please enter the base URL (if using ollama, please fill in localhost:11434/v1): {color_end}")
    key = c.input(f"{color}Please enter your API_KEY (if using ollama, fill in freely): {color_end}")
    model = c.input(f"{color}Please enter the model (enter LIST to select, PULL to pull new): {color_end}")
    if model=="LIST":
        lst = subprocess.run(shlex.split("ollama list"),text=True,capture_output=True).stdout.splitlines()
        for i in range(1,len(lst),2):
            c.print(str(i)+" "+lst[i])
        choose = c.input("Which one do you prefer?")
        model = lst[i].split(" ")[0]
    if model=="PULL":
        model = c.input("What model do you want to pull?")
        subprocess.Popen(shlex.split("ollama pull "+model),stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr)


    with open(config_path, 'w') as f:
        f.write(f'CODEMAX_HOST={url}\n')
        f.write(f'CODEMAX_KEY={key}\n')
        f.write(f'CODEMAX_MODEL={model}\n')

    c.print(f"{color}Configuration saved successfully!{color_end}")
    #c.print(f"[green]Please run [bold]source {config_path}[/bold] to apply the environment variables.[/green]")

if __name__ == "__main__":
    main()