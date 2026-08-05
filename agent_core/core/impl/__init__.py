# -*- coding: utf-8 -*-
"""
Default implementations of shared components.

This module contains the default implementations for all shared components.
Each implementation accepts optional hooks for agent-specific behavior.

Structure:
    impl/
    ├── action/         # ActionExecutor, ActionManager
    ├── context/        # ContextEngine
    ├── database/       # DatabaseInterface
    ├── event_stream/   # EventStream, EventStreamManager
    ├── llm/            # LLMInterface and providers
    ├── memory/         # MemoryManager
    ├── state/          # StateManager (extends existing state module)
    └── session/        # SessionManager (extends existing session module)
"""
