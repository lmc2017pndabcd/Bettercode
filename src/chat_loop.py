#coding:utf-8
import os
import json
import re
from rich.console import Console
from rich.markdown import Markdown
from openai import OpenAI
import locale


console = Console()
cfglist = {}
with open(os.path.expanduser("~/.codemax"), 'r') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'): 
            continue
        if line.startswith('export '):
            line = line[7:] 
        if '=' in line:
            key, value = line.split('=', 1)
            cfglist[key.strip()] = value.strip()

client = OpenAI(api_key=cfglist["CODEMAX_KEY"], base_url=cfglist["CODEMAX_HOST"])
tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "read file on this computer",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "The relative or absolute path of the file"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "write file on this computer",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "The relative or absolute path of the file"},
                    "content": {"type": "string", "description": "The complete content to be written"}
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {"type":"web_search"}
]


def execute_tool(name, arguments):
    if name == "read_file":
        try:
            with open(arguments["file_path"], "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"FAILURE: {str(e)}"
    
    elif name == "write_file":
        try:
            # dir_name = os.path.dirname(arguments['file_path'])
            # if dir_name and not os.path.exists(dir_name):
            #     os.makedirs(dir_name, exist_ok=True)
                
            with open(arguments['file_path'], 'w', encoding='utf-8') as f:
                f.write(arguments["content"])

            return f"SUCCESS: {arguments['file_path']}"
        except Exception as e:
            return f"FAILURE: {str(e)}"
    return "Unknown Tool!"

def chat_loop():
    system_prompt = f"""You are a professional AI programming assistant.
When the user requests to view the code, please call the read_file tool.
When users request to modify, create, or save code, please call the write_file tool.
Special note: Due to the use of the 'w' mode in write_file, please fill in the complete content when using write_file.
Explain and talk in {locale.getdefaultlocale() if locale.getdefaultlocale()[0] else 'en_US'}(i18n), but variable names, code snippets, and technical terms can be in American English"""
    
    messages = [{"role": "system", "content": system_prompt}]
    
    while True:
        user_input = console.input("[bold green]You:[/bold green] ")
        if user_input.lower() in ["exit", "quit", "bye"]: 
            break
            
        messages.append({"role": "user", "content": user_input})
        
        try:
            response = client.chat.completions.create(
                model=cfglist["CODEMAX_MODEL"], 
                messages=messages, 
                tools=tools, 
                tool_choice="auto"
            )
            
            assistant_message = response.choices[0].message
            raw_content = assistant_message.content or ""
            
            if assistant_message.tool_calls:
                messages.append(assistant_message)
                for tool_call in assistant_message.tool_calls:
                    func_name = tool_call.function.name
                    try:
                        func_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError as e:
                        console.print(f"[red]❌ Parse Error: {e}[/red]")
                        func_args = {}
                    
                    console.print(f"[yellow]⚙️ Execute: {func_name}({func_args})[/yellow]")
                    tool_result = execute_tool(func_name, func_args)
                    
                    messages.append({
                        "role": "tool", 
                        "tool_call_id": tool_call.id, 
                        "content": str(tool_result)
                    })
                
                final_response = client.chat.completions.create(
                    model=cfglist["CODEMAX_MODEL"], 
                    messages=messages
                )
                final_text = final_response.choices[0].message.content
                console.print(Markdown(f"**AI:** {final_text}"))
                messages.append({"role": "assistant", "content": final_text})
            elif ('"name": "read_file"' in raw_content or 
                  '"name": "write_file"' in raw_content):
                try:
                    json_str = re.search(r'\{.*\}', raw_content, re.DOTALL)
                    if json_str:
                        parsed = json.loads(json_str.group())
                        func_name = parsed.get("name")
                        func_args = parsed.get("arguments", {})
                        
                        if func_name and func_args:
                            console.print(f"[yellow]⚙️ Execute: {func_name}({func_args})[/yellow]")
                            tool_result = execute_tool(func_name, func_args)
                            
                            messages.append({"role": "user", "content": f"Result: {tool_result}\nContinue."})
                            continue
                except Exception as e:
                    console.print(f"[red]❌ ERROR: {e}[/red]")
            
            else:
                console.print(Markdown(f"**AI:** {raw_content}"))
                messages.append({"role": "assistant", "content": raw_content})
                
        except Exception as e:
            console.print(f"[red]❌ API ERROR: {e}[/red]")