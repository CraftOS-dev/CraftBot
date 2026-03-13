from agent_core import action

# Input schema for memory search
_INPUT_SCHEMA = {
    "query": {
        "type": "string",
        "example": "user preferences for communication",
        "description": "The semantic search query to find relevant memory."
    },
    "top_k": {
        "type": "integer",
        "example": 5,
        "description": "Maximum number of results to return. Defaults to 5.",
        "default": 5
    }
}

# Output schema for memory search
_OUTPUT_SCHEMA = {
    "status": {
        "type": "string",
        "example": "ok",
        "description": "Indicates the action completed successfully."
    },
    "results": {
        "type": "array",
        "description": "List of memory pointers with chunk_id, file_path, section_path, title, summary, and relevance_score.",
        "example": [
            {
                "chunk_id": "MEMORY.md_memory_1",
                "file_path": "MEMORY.md",
                "section_path": "Memory",
                "title": "User Preference",
                "summary": "John prefers dark mode interfaces",
                "relevance_score": 0.85
            }
        ]
    },
    "count": {
        "type": "integer",
        "example": 5,
        "description": "Number of results returned."
    }
}


@action(
    name="memory_search",
    description="Search the agent's memory for relevant information based on a semantic query. Returns memory pointers with file paths, section paths, titles, summaries, and relevance scores. Use this to recall past events, user preferences, decisions, and learned facts.",
    mode="ALL",
    platforms=["linux", "windows", "darwin"],
    action_sets=["core"],
    input_schema=_INPUT_SCHEMA,
    output_schema=_OUTPUT_SCHEMA,
    test_payload={
        "query": "user preferences",
        "top_k": 5,
        "simulated_mode": True
    }
)
def memory_search(input_data: dict) -> dict:
    """
    Search the agent's memory for relevant information.

    This action uses the MemoryManager to perform semantic search across
    the agent's indexed files (MEMORY.md, EVENT_UNPROCESSED.md, etc.).
    """
    simulated_mode = input_data.get('simulated_mode', False)

    if simulated_mode:
        return {
            'status': 'ok',
            'results': [
                {
                    "chunk_id": "MEMORY.md_memory_1",
                    "file_path": "MEMORY.md",
                    "section_path": "Memory",
                    "title": "Test Memory",
                    "summary": "This is a test memory result",
                    "relevance_score": 0.90
                }
            ],
            'count': 1
        }

    try:
        # Check if memory is enabled
        from app.ui_layer.settings.memory_settings import is_memory_enabled
        if not is_memory_enabled():
            return {
                'status': 'ok',
                'results': [],
                'count': 0,
                'message': 'Memory is disabled'
            }

        query = input_data.get('query')
        if not query:
            return {
                'status': 'error',
                'results': [],
                'count': 0,
                'error': 'query is required'
            }

        top_k = input_data.get('top_k', 5)
        try:
            top_k = int(top_k)
            if top_k < 1:
                top_k = 5
        except (TypeError, ValueError):
            top_k = 5

        # Import here to avoid issues with dynamic module loading
        from app.internal_action_interface import InternalActionInterface

        # Call the InternalActionInterface method
        results = InternalActionInterface.memory_search(query=query, top_k=top_k)

        return {
            'status': 'ok',
            'results': results,
            'count': len(results)
        }

    except RuntimeError as e:
        # MemoryManager not initialized
        return {
            'status': 'error',
            'results': [],
            'count': 0,
            'error': str(e)
        }
    except Exception as e:
        return {
            'status': 'error',
            'results': [],
            'count': 0,
            'error': str(e)
        }
