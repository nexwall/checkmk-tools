import subprocess
result = subprocess.run(['su', '-', 'monitoring', '-c', 'cmk -R'], capture_output=True, text=True)
print(result.stdout)
print(result.stderr)
print("Exit:", result.returncode)
