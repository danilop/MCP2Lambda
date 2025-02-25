import base64
import json
import os
import subprocess
import sys
import io

TMP_DIR = "/tmp"


def remove_tmp_contents() -> None:
    """
    Remove all contents (files and directories) from the temporary directory.

    This function traverses the /tmp directory tree and removes all files and empty
    directories. It handles exceptions for each removal attempt and prints any
    errors encountered.
    """
    # Traverse the /tmp directory tree
    for root, dirs, files in os.walk(TMP_DIR, topdown=False):
        # Remove files
        for file in files:
            file_path: str = os.path.join(root, file)
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error removing {file_path}: {e}")
        
        # Remove empty directories
        for dir in dirs:
            dir_path: str = os.path.join(root, dir)
            try:
                os.rmdir(dir_path)
            except Exception as e:
                print(f"Error removing {dir_path}: {e}")


def do_install_modules(modules: list[str], current_env: dict[str, str]) -> str:    
    """
    Install Python modules using pip.

    This function takes a list of module names and attempts to install them
    using pip. It handles exceptions for each module installation and prints
    any errors encountered.

    Args:
        modules (list[str]): A list of module names to install.
    """

    output = ''

    for module in modules:
        try:
            subprocess.run(["pip", "install", module], check=True)
        except Exception as e:
            print(f"Error installing {module}: {e}")

    if type(modules) is list and len(modules) > 0:
        current_env["PYTHONPATH"] = TMP_DIR
        try:
            _ = subprocess.run(f"pip install -U pip setuptools wheel -t {TMP_DIR} --no-cache-dir".split(), capture_output=True, text=True, check=True)
            for module in modules:
                _ = subprocess.run(f"pip install {module} -t {TMP_DIR} --no-cache-dir".split(), capture_output=True, text=True, check=True)
        except Exception as e:
            error_message = f"Error installing {module}: {e}"
            print(error_message)
            output += error_message

    return output


def lambda_handler(event: dict, context: dict) -> dict:
    """
    AWS Lambda function handler to execute Python code provided in the event.
    
    Args:
        event (dict): The Lambda event object containing the Python code to execute
                      Expected format: {"code": "your_python_code_as_string"}
        context (dict): AWS Lambda context object
        
    Returns:
        dict: Results of the code execution containing:
              - status (str): "success" or "error"
              - output (str): Output of the executed code or error message
    """
    try:
        code = event.get('code', '')
        
        # Capture stdout
        old_stdout = sys.stdout
        redirected_output = io.StringIO()
        sys.stdout = redirected_output
        
        # Execute the code
        exec(code)
        sys.stdout = old_stdout
        output = redirected_output.getvalue()
        
        return {
            "status": "success",
            "output": output
        }
    except Exception as e:
        return {
            "status": "error",
            "output": str(e)
        }
