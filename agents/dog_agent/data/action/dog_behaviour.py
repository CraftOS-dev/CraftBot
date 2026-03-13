from agent_core import action

@action(
        name="bark",
        description="Use this action to send message to users by barking, instead of human speech.",
        execution_mode="internal",
        input_schema={
                "message": {
                        "type": "string",
                        "example": "Woof wooofff wooff woooof woof!",
                        "description": "Bark to the user."
                },
                "wait_for_user_reply": {
                        "type": "boolean",
                        "example": True,
                        "description": "True if this action require user's response to proceed. For example, true if you ask a question in the message."
                }
        },
        output_schema={
                "status": {
                        "type": "string",
                        "example": "ok",
                        "description": "Indicates the action completed successfully."
                },
                "message": {
                        "type": "string",
                        "example": "Woof wooofff wooff woooof woof!",
                        "description": "Bark to the user."
                },
                "fire_at_delay": {
                        "type": "number",
                        "example": 10800,
                        "description": "Delay in seconds before the next follow-up action should be scheduled. 10800 seconds (3 hours) if wait_for_user_reply is true, otherwise 0."
                }
        },
        test_payload={
                "question": "Woof wooofff wooff woooof woof?",
                "wait_for_user_reply": False,
                "simulated_mode": True
        }
)
def bark(input_data: dict) -> dict:
    import json
    import asyncio
    
    message = input_data['message']
    wait_for_user_reply = bool(input_data.get('wait_for_user_reply', False))
    
    import app.internal_action_interface as internal_action_interface
    asyncio.run(internal_action_interface.InternalActionInterface.do_chat(message))
    
    fire_at_delay = 10800 if wait_for_user_reply else 0
    return {'status': 'success', 'message': message, 'fire_at_delay': fire_at_delay}

@action(
    name="sit",
    description="Display an ASCII image of a dog sitting.",
    execution_mode="internal",
    input_schema={}, 
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Indicates the action completed successfully."
        }
    },
    test_payload={
        "simulated_mode": True
    }
)
def sit(input_data: dict) -> dict:
    import asyncio
    import app.internal_action_interface as internal_action_interface

    dog_ascii = r""".
          __
       __()'`;
     //,   /`
     /_)_-||
"""

    asyncio.run(internal_action_interface.InternalActionInterface.do_chat(dog_ascii))
    return {"status": "success"}


from agent_core import action

@action(
    name="wiggle tail",
    description="Display an ASCII image of a dog sitting and wiggling its tail.",
    execution_mode="internal",
    input_schema={}, 
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Indicates the action completed successfully."
        }
    },
    test_payload={
        "simulated_mode": True
    }
)
def wiggle_tail(input_data: dict) -> dict:
    import asyncio
    import app.internal_action_interface as internal_action_interface

    dog_ascii = r""".
           __
     (~(__()'`;       
      /,    /`   
      \\"--\\   
"""

    asyncio.run(internal_action_interface.InternalActionInterface.do_chat(dog_ascii))
    return {"status": "success"}


@action(
    name="eat",
    description="Display an ASCII image of a dog eating and making nom nom noise.",
    execution_mode="internal",
    input_schema={
            "nom_nom_noise": {
                    "type": "string",
                    "example": "Nom nom nom",
                    "description": "The nom nom noise depending on the portion of food."
            },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Indicates the action completed successfully."
        },
        "nom_nom_noise": {
            "type": "string",
            "example": "Nom nom nom",
            "description": "The nom nom noise depending on the portion of food."
        },
    },
    test_payload={
        "simulated_mode": True
    }
)
def eat(input_data: dict) -> dict:
    import asyncio
    import app.internal_action_interface as internal_action_interface

    dog_ascii = r""".
           __
      (___()'`;       
      /,    /`   ____
      \\"--\\   /_oo \
                \____/
"""
    nom_nom_noise = input_data['nom_nom_noise']
    asyncio.run(internal_action_interface.InternalActionInterface.do_chat(dog_ascii))
    asyncio.run(internal_action_interface.InternalActionInterface.do_chat(nom_nom_noise))
    return {"status": "success", "nom_nom_noise": nom_nom_noise}
    
    
@action(
    name="sniff",
    description="Display an ASCII sniffing animation, then announce what the dog found.",
    execution_mode="internal",
    input_schema={
        "found": {
            "type": "string",
            "example": "a bone",
            "description": "What the dog found after sniffing."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Indicates the action completed successfully."
        },
        "found": {
            "type": "string",
            "example": "a bone",
            "description": "What the dog found after sniffing."
        },
        "message": {
            "type": "string",
            "example": "*dog found a bone*",
            "description": "Formatted message announcing what the dog found."
        }
    },
    test_payload={
        "found": "a bone",
        "simulated_mode": True
    }
)
def sniff(input_data: dict) -> dict:
    import asyncio
    import time
    import app.internal_action_interface as internal_action_interface

    found = input_data["found"]
    message = f"*dog found {found}*"

    frames = [
        r""".
           __
      (___()'`;
      /,    /`    ~
      \\"--\\
""",
        r""".
           __
      (___()'`;   ~ ~
      /,    /`    ~
      \\"--\\
""",
        r""".
           __
      (___()'`;  ~ ~ ~
      /,    /`   ~ ~
      \\"--\\
"""
    ]

    for f in frames:
        asyncio.run(internal_action_interface.InternalActionInterface.do_chat(f))
        time.sleep(10)

    asyncio.run(internal_action_interface.InternalActionInterface.do_chat(message))
    return {"status": "success", "found": found, "message": message}
    
    
@action(
    name="dig",
    description="Display an ASCII digging animation, then announce what the dog found.",
    execution_mode="internal",
    input_schema={
        "found": {
            "type": "string",
            "example": "a buried toy",
            "description": "What the dog found after digging."
        },
        "dig_seconds": {
            "type": "number",
            "example": 4,
            "description": "How long the dog digs (seconds). Clamped to 3–5 seconds."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Indicates the action completed successfully."
        },
        "found": {
            "type": "string",
            "example": "a buried toy",
            "description": "What the dog found after digging."
        },
        "message": {
            "type": "string",
            "example": "*dog found a buried toy*",
            "description": "Formatted message announcing what the dog found."
        },
        "dig_seconds": {
            "type": "number",
            "example": 4,
            "description": "Actual digging duration used (seconds), after clamping."
        }
    },
    test_payload={
        "found": "a buried toy",
        "dig_seconds": 4,
        "simulated_mode": True
    }
)
def dig(input_data: dict) -> dict:
    import asyncio
    import time
    import app.internal_action_interface as internal_action_interface

    found = input_data["found"]
    message = f"*dog found {found}*"

    try:
        dig_seconds = float(input_data.get("dig_seconds", 5))
    except (TypeError, ValueError):
        dig_seconds = 5.0
    dig_seconds = max(5.0, min(10.0, dig_seconds))

    frames = [
        r""".
           __
      (___()'`;
      /,    /`  
      \\"--\\
            
""",
        r""".
           __
      (___()'`;   
      /,    \\  
      \\"--` \\ ' "
             
""",
        r""".
           __
      (___()'`;
      /,    /`  
      \\"--\\ " '  
        
""",
        r""".
           __
      (___()'`;   
      /,    \\  
      \\"--` \\ '"
             
"""
    ]

    frame_delay = 3
    total_frames = int(dig_seconds / frame_delay)
    for i in range(total_frames):
        f = frames[i % 4]
        asyncio.run(internal_action_interface.InternalActionInterface.do_chat(f))
        time.sleep(frame_delay)

    asyncio.run(internal_action_interface.InternalActionInterface.do_chat(message))
    return {"status": "success", "found": found, "message": message, "dig_seconds": dig_seconds}