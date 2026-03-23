import os
import sys

def main():
    print("Testing ADK Agent and Vizier Client...")
    
    # Check for GCP credentials
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print("WARNING: GOOGLE_APPLICATION_CREDENTIALS not set. Vertex AI / Vizier calls will likely fail with auth errors.")
        print("To run for real, set this environment variable to a valid service account JSON key.")
    
    try:
        from app.agents.adk_operator import build_adk_operator_agent
        print("\n[1] Building ADK Agent...")
        agent = build_adk_operator_agent()
        print("Agent built successfully.")
        
        print("\n[2] Testing Agent Invocation (Conjunction Check)...")
        # In a real environment, this would call vertex. Without auth, the LLM call will fail.
        # We'll try to invoke it.
        try:
            response = agent.invoke({"input": "What are the current threats for satellite 61046? Just check the conjunctions, do not optimize yet."})
            print(f"Agent Response: {response['output']}")
        except Exception as e:
            print(f"Agent invocation skipped/failed (Expected if no GCP auth): {e}")

    except ImportError as e:
        print(f"Import Error: {e}. Make sure you are running from the 'dissertacao' directory.")

if __name__ == "__main__":
    main()
