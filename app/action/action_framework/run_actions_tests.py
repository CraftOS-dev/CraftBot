import sys
import os
import platform
import logging
import json

# Set up environment paths
sys.path.append(os.getcwd())

# Configure helpful output logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("TestRunner")

from agent_core import load_actions_from_directories, registry_instance

def run_tests():
    current_os = platform.system().lower()
    logger.info(f"========================================")
    logger.info(f"Action Test Runner Starting on: {current_os}")
    logger.info(f"========================================\n")

    # 1. Initialize: Load all actions from folders
    logger.info("-> Discovering actions...")
    # You might need to adjust paths here depending on your exact structure
    # load_actions_from_directories(paths_to_scan=['core/action/data/action', ...]) 
    load_actions_from_directories() 
    logger.info("-> Discovery complete.\n")

    # 2. Retrieve testable actions for current OS
    logger.info(f"-> Finding testable actions for platform '{current_os}'...")
    testable_actions = registry_instance.get_testable_actions(current_os)
    
    if not testable_actions:
        logger.warning("No actions marked with 'test_payload' found for this platform.")
        return

    logger.info(f"-> Found {len(testable_actions)} testable actions. Starting execution...\n")

    # 3. Execution Loop
    success_count = 0
    fail_count = 0

    for i, action_impl in enumerate(testable_actions, 1):
        meta = action_impl.metadata
        logger.info(f"----------------------------------------")
        logger.info(f"TEST {i}/{len(testable_actions)}: Action '{meta.name}'")
        logger.info(f"Platform implementation: {meta.platforms}")
        logger.info(f"Input Payload: {meta.test_payload}")
        logger.info(f"----------------------------------------")

        try:
            # EXECUTE THE ACTION HANDLER WITH TEST PAYLOAD
            result = action_impl.handler(meta.test_payload)
            
            # Basic validation: Did it return a dict?
            if result is None:
                logger.error(f"❌ TEST FAILED. Action returned None.")
                fail_count += 1
            elif isinstance(result, dict):
                status = result.get("status")
                # Accept both 'success' and 'ok' as valid success statuses
                # Also accept actions that return a dict without status field (assume success)
                if status in ("success", "ok") or (status is None and len(result) > 0):
                    logger.info(f"✅ TEST PASSED. Result output:")
                    # Pretty print the result dict nicely
                    logger.info(json.dumps(result, indent=2))
                    success_count += 1
                elif status == "error":
                    logger.error(f"❌ TEST FAILED. Action returned error status.")
                    logger.error(f"Output: {result}")
                    fail_count += 1
                else:
                    # Other status values (like 'ignored') - check if it's a valid completion
                    if status in ("ignored", "completed", "queued"):
                        logger.info(f"✅ TEST PASSED. Result output:")
                        logger.info(json.dumps(result, indent=2))
                        success_count += 1
                    else:
                        logger.error(f"❌ TEST FAILED. Action finished but status was not 'success' or 'ok'.")
                        logger.error(f"Output: {result}")
                        fail_count += 1
            else:
                logger.error(f"❌ TEST FAILED. Action did not return a dict.")
                logger.error(f"Output: {result} (type: {type(result).__name__})")
                fail_count += 1

        except Exception as e:
            logger.error(f"❌ TEST FAILED WITH EXCEPTION.")
            logger.error(f"Error: {str(e)}")
            # Optionally print traceback here
            # import traceback
            # traceback.print_exc()
            fail_count += 1
        
        logger.info("\n")

    # 4. Summary
    logger.info("========================================")
    logger.info("Testing Summary")
    logger.info("========================================")
    logger.info(f"Total Tests: {len(testable_actions)}")
    logger.info(f"Passed:      {success_count}")
    logger.info(f"Failed:      {fail_count}")
    logger.info("========================================")
    
    if fail_count > 0:
        sys.exit(1) # Exit with error code for CI/CD pipelines

if __name__ == "__main__":
    run_tests()