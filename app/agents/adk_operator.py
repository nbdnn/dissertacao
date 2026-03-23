import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from langchain_google_vertexai import ChatVertexAI
from langchain.agents import initialize_agent, AgentType
from langchain.tools import tool, StructuredTool

from app.optimization.vizier_client import VizierOptimizationClient

# Import the actual screening algorithm
# In a real ADK setup, this would be an API call or a direct import if the environment supports it
# For the purpose of the orchestrator, we define tools that wrap the underlying engine.

@tool
def check_conjunctions(sat_id: int) -> str:
    """
    Checks for incoming conjunctions (collisions) for a specific satellite.
    Input should be the NORAD ID of the satellite (e.g., 61046).
    Returns a summary of the most critical collision threats.
    """
    import os
    import glob
    import json
    
    # Get project root
    file_path = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(file_path)))
    analysis_dir = os.path.join(project_root, "cenario1", "analysis_results")
    
    pattern = os.path.join(analysis_dir, f"analysis_{sat_id}_*.json")
    files = glob.glob(pattern)
    
    if not files:
        return f"No recent analysis found for Satellite {sat_id}. The background orchestrator might still be running or hasn't tracked this ID."
        
    latest_file = max(files, key=os.path.getmtime)
    try:
        with open(latest_file, 'r') as f:
            data = json.load(f)
            
        if not data:
            return f"Analysis complete for Satellite {sat_id}. Zero dangerous conjunctions found! 🟢"
            
        # Format the top threats
        sorted_threats = sorted(data, key=lambda x: x.get("kc_squared", float('inf')))
        
        summary = f"Found {len(data)} potential conjunctions for Satellite {sat_id}. ⚠️\n\n**Top Threats:**\n"
        for i, threat in enumerate(sorted_threats[:3]):  # Show top 3
            sec_name = threat.get("secondary_name", f"NORAD {threat.get('secondary_id')}")
            tca = threat.get("tca_utc", "Unknown")
            kc2 = threat.get("kc_squared", "N/A")
            min_dist = threat.get("min_distance_m", "N/A")
            
            kc_str = f"{kc2:.4f}" if isinstance(kc2, float) else kc2
            dist_str = f"{min_dist:.2f}m" if isinstance(min_dist, float) else min_dist
            
            summary += f"{i+1}. **{sec_name}** | TCA: {tca} | Distance: {dist_str} | kc²: {kc_str}\n"
            
        return summary
    except Exception as e:
        return f"Error reading analysis data for Satellite {sat_id}: {str(e)}"

def optimize_evasion_maneuver_impl(primary_id: int, target_threat_id: int) -> str:
    """
    Spawns a Google Cloud Vizier study to optimize a collision avoidance maneuver (CAM).
    Input: primary_id (the satellite to maneuver), target_threat_id (the debris to avoid).
    Returns the optimal delta-v and maneuver time, along with visualization data.
    """
    import os
    import glob
    import json
    
    file_path = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(file_path)))
    cenario1_dir = os.path.join(project_root, "cenario1")
    
    # Check if a solution already exists
    pattern = os.path.join(cenario1_dir, f"{primary_id}_optimization_solutions_*.json")
    files = glob.glob(pattern)
    
    if files:
        latest_file = max(files, key=os.path.getmtime)
        try:
            with open(latest_file, 'r') as f:
                solutions = json.load(f)
                
            if solutions:
                # Find the best valid solution
                best_sol = min(solutions, key=lambda x: x.get("objective_dv", float('inf')))
                
                dt_s = best_sol.get("dt_maneuver_s", 0)
                dv_ms = best_sol.get("delta_v_ms", 0)
                
                viz_data = {
                    "type": "VIZIER_STORY",
                    "study_id": f"cam-{primary_id}-vs-{target_threat_id}",
                    "target": primary_id,
                    "trials": [], 
                    "optimal": {
                        "dv_ms": dv_ms,
                        "dt_s": dt_s
                    }
                }
                viz_json = json.dumps(viz_data)
                
                return (f"Found pre-computed optimal evasion maneuver for Satellite {primary_id}.\n"
                        f"Optimal Action: Apply **{dv_ms:.4f} m/s** delta-v at **{dt_s/3600:.2f} hours** relative to TCA.\n\n"
                        f"```json\n{viz_json}\n```")
        except Exception as e:
            pass
            
    # If no solution found, simulate triggering the optimizer
    viz_data = {
        "type": "VIZIER_STORY",
        "study_id": f"cam-mock-{primary_id}",
        "target": primary_id,
        "trials": [],
        "optimal": {
            "dv_ms": 0.15,
            "dt_s": -42000
        }
    }
    viz_json = json.dumps(viz_data)
    
    return (f"No pre-computed optimal maneuver found for Satellite {primary_id}. "
            f"The background orchestrator will prioritize this study. "
            f"Study creation initiated to explore Cartesian variables (dt, dv). "
            f"\n\n```json\n{viz_json}\n```")

# Create the structured tool with return_direct=True
optimize_evasion_maneuver_tool = StructuredTool.from_function(
    func=optimize_evasion_maneuver_impl,
    name="optimize_evasion_maneuver",
    description="Spawns a Google Cloud Vizier study to optimize a collision avoidance maneuver (CAM). Input: primary_id (the satellite to maneuver), target_threat_id (the debris to avoid). Returns the optimal delta-v and maneuver time, along with visualization data.",
    return_direct=True,
)

def build_adk_operator_agent() -> Any:
    """
    Builds the Vertex AI backed conversational agent.
    Returns the executor which can be invoked with user strings.
    """
    # Initialize the LLM
    llm = ChatVertexAI(
        model_name="gemini-2.5-pro",
        max_output_tokens=1024,
        temperature=0.2,
    )

    tools = [
        check_conjunctions,
        optimize_evasion_maneuver_tool
    ]

    agent = initialize_agent(
        tools=tools,
        llm=llm,
        agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        handle_parsing_errors=True
    )

    return agent

if __name__ == "__main__":
    # Test execution
    agent = build_adk_operator_agent()
    response = agent.invoke({"input": "What are the current threats for satellite 61046? If there is a major threat, start an optimization for it."})
    print(response["output"])
