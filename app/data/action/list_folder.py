from agent_core import action

@action(
        name="list_folder",
        description="Lists the contents of a specified folder/directory. Use absolute paths.",
        mode="CLI",
        action_sets=["core"],
        input_schema={
                "path": {
                        "type": "string",
                        "example": "C:/Users/user/Documents",
                        "description": "Absolute path to the folder to list. Use full absolute paths (e.g., C:/Users/user/Documents on Windows or /home/user/documents on Linux/Mac)."
                }
        },
        output_schema={
                "status": {
                        "type": "string",
                        "example": "success",
                        "description": "Indicates the result of the list operation"
                },
                "contents": {
                        "type": "array",
                        "example": [
                                "file1.txt",
                                "subfolder",
                                "image.png"
                        ],
                        "description": "List of files/folders contained in the specified directory"
                },
                "message": {
                        "type": "string",
                        "description": "Error message if status is 'error'"
                }
        },
        test_payload={
                "path": "C:/Users/user/Documents",
                "simulated_mode": True
        }
)
def list_folder(input_data: dict) -> dict:
    import os, json

    path = input_data['path']
    simulated_mode = input_data.get('simulated_mode', False)
    
    if simulated_mode:
        # Return mock result for testing
        return {'status': 'success', 'contents': ['file1.txt', 'file2.txt', 'subfolder']}
    
    try:
        contents = os.listdir(path)
        return {'status': 'success', 'contents': contents}
    except Exception as e:
        return {'status': 'error', 'contents': [], 'message': str(e)}