"""Print the analysis graph as a Mermaid diagram (paste it in the README or a docs page).

Run from backend/:  python -m scripts.draw_analysis_graph
It is generated from the code, so it cannot drift: tests/test_judge.py checks the same topology.
"""

from app.analysis.graph import build_analysis_graph

if __name__ == "__main__":
    print(build_analysis_graph(None, None, None).get_graph().draw_mermaid())  # type: ignore[arg-type]
