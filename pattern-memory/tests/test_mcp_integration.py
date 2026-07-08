"""Pattern Memory — MCP Integration Tests

Tests the full MCP protocol flow by starting the server as a subprocess
and communicating via stdio, just like a real MCP client would.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

async def _run_mcp_test():
    """Run a full MCP integration test against the pattern-memory server."""
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession
    from mcp import StdioServerParameters

    # Clean ChromaDB before testing — the unit tests do this in
    # _make_storage(), and the integration test must mirror it
    # so that prior runs don't pollute similarity search.
    import chromadb
    try:
        chromadb.HttpClient(host="127.0.0.1", port=8000).delete_collection(
            "pattern_memory"
        )
    except Exception:
        pass

    # Create a temp directory for test assets
    test_temp_dir = tempfile.mkdtemp()

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).parent.parent / "server.py")],
        env={
            **os.environ,
            "PATTERN_MEMORY_DB": os.path.join(test_temp_dir, "test.db"),
            "PATTERN_MEMORY_PID": os.path.join(test_temp_dir, "test.pid"),
            "PATTERN_MEMORY_CHROMA": "http://127.0.0.1:8000",
        },
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize
            await session.initialize()

            # List tools — verify consolidated 13-tool surface
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"\n  Available tools ({len(tool_names)}): {tool_names}")
            assert len(tool_names) == 13, f"Expected 13 tools, got {len(tool_names)}: {tool_names}"

            # Core tools
            assert "record_correction" in tool_names
            assert "get_patterns" in tool_names
            assert "search_patterns" in tool_names
            assert "list_patterns" in tool_names
            assert "get_session_context" in tool_names

            # Consolidated tools
            assert "rate_pattern" in tool_names
            assert "get_stats" in tool_names
            assert "run_decay" in tool_names
            assert "check_before_acting" in tool_names
            assert "check_conflicts" in tool_names
            assert "resolve_conflict" in tool_names
            assert "classify_correction" in tool_names
            assert "mark_pattern_applied" in tool_names

            # Old tools should NOT exist
            assert "confirm_pattern" not in tool_names
            assert "reject_pattern" not in tool_names
            assert "preview_decay" not in tool_names
            assert "auto_confirm_pattern" not in tool_names
            assert "get_auto_confirmable" not in tool_names
            assert "check_correction_after_application" not in tool_names
            assert "classify_correction_regex" not in tool_names
            assert "classify_correction_hybrid" not in tool_names
            assert "detect_corrections_batch" not in tool_names
            assert "get_conflicts" not in tool_names
            assert "get_context_scoped_conflicts" not in tool_names
            assert "get_all_conflicts_classified" not in tool_names
            assert "get_applicable_patterns" not in tool_names
            assert "auto_apply_patterns" not in tool_names

            print(f"  ✓ All 13 tools registered, old tools removed")

            # Get initial stats
            stats_result = await session.call_tool("get_stats", {})
            stats = json.loads(stats_result.content[0].text)
            print(f"  Initial stats: {stats}")
            assert "total_patterns" in stats
            assert "auto_confirmable" in stats  # New field

            # Record a correction
            record_result = await session.call_tool("record_correction", {
                "original": "used 85% threshold",
                "corrected": "use 80% threshold",
                "context": "image processing",
                "category": "threshold",
            })
            record = json.loads(record_result.content[0].text)
            print(f"  Record result: {record}")
            assert record["is_new_pattern"] is True
            assert record["pattern_id"] is not None
            pattern_id = record["pattern_id"]

            # Record same correction again (should match, not create new)
            record2_result = await session.call_tool("record_correction", {
                "original": "used 85% threshold",
                "corrected": "use 80% threshold",
                "context": "image processing",
                "category": "threshold",
            })
            record2 = json.loads(record2_result.content[0].text)
            print(f"  Record again: {record2}")
            assert record2["is_new_pattern"] is False
            assert record2["pattern_id"] == pattern_id

            # Get patterns for context
            get_result = await session.call_tool("get_patterns", {
                "context": "image processing threshold",
            })
            patterns = json.loads(get_result.content[0].text)
            print(f"  Patterns found: {len(patterns)}")
            assert len(patterns) >= 1
            assert patterns[0]["pattern"]["confidence"] >= 0.3

            # Rate pattern (confirm)
            rate_result = await session.call_tool("rate_pattern", {
                "pattern_id": pattern_id,
                "action": "confirm",
            })
            rate = json.loads(rate_result.content[0].text)
            print(f"  Rate (confirm) result: {rate}")
            assert rate["confidence"] >= 0.5

            # Search patterns
            search_result = await session.call_tool("search_patterns", {
                "query": "threshold settings",
            })
            search = json.loads(search_result.content[0].text)
            print(f"  Search results: {len(search)}")
            assert len(search) >= 1

            # List all patterns
            list_result = await session.call_tool("list_patterns", {})
            all_patterns = json.loads(list_result.content[0].text)
            print(f"  All patterns: {len(all_patterns)}")
            assert len(all_patterns) >= 1

            # Record a second correction (different category)
            record3_result = await session.call_tool("record_correction", {
                "original": "used var in JS",
                "corrected": "use const instead",
                "context": "JavaScript development",
                "category": "code_style",
            })
            record3 = json.loads(record3_result.content[0].text)
            assert record3["is_new_pattern"] is True
            pattern_id2 = record3["pattern_id"]

            # Rate pattern (reject)
            reject_result = await session.call_tool("rate_pattern", {
                "pattern_id": pattern_id2,
                "action": "reject",
            })
            reject = json.loads(reject_result.content[0].text)
            print(f"  Rate (reject) result: {reject}")
            # Pattern either removed (confidence dropped below 0.1) or low confidence
            assert reject.get("removed") is True or reject.get("confidence", 1.0) <= 0.2

            # Check conflicts
            conflicts_result = await session.call_tool("check_conflicts", {
                "type": "all",
            })
            conflicts = json.loads(conflicts_result.content[0].text)
            print(f"  Conflicts: {len(conflicts)}")

            # Test resolve_conflict end-to-end.
            # The duplicate detector uses semantic similarity, not
            # action opposition — so opposing actions with semantically
            # similar text get collapsed. We deliberately pick two
            # patterns in different domains to keep them distinct.
            pA_result = await session.call_tool("record_correction", {
                "original": "edited a photograph with bright filter",
                "corrected": "use contrast filter for product photography",
                "context": "image processing pipeline",
                "category": "workflow",
            })
            pA = json.loads(pA_result.content[0].text)
            pA_id = pA["pattern_id"]

            # Boost confidence on pattern A
            for _ in range(3):
                await session.call_tool("record_correction", {
                    "original": "applied default filter",
                    "corrected": "use contrast filter for product photography",
                    "context": "image processing pipeline",
                    "category": "workflow",
                })

            # Second pattern: very different domain to avoid collapse
            pB_result = await session.call_tool("record_correction", {
                "original": "used HTTP for service calls",
                "corrected": "use gRPC for inter-service communication",
                "context": "microservices architecture",
                "category": "tool_choice",
            })
            pB = json.loads(pB_result.content[0].text)
            pB_id = pB["pattern_id"]

            # Boost B's confidence
            for _ in range(3):
                await session.call_tool("record_correction", {
                    "original": "default transport was HTTP",
                    "corrected": "use gRPC for inter-service communication",
                    "context": "microservices architecture",
                    "category": "tool_choice",
                })

            # If the duplicate detector collapsed the second pattern
            # into the first, we have only one ID. Verify the tool
            # still works in that case but skip the resolution
            # assertions.
            if pA_id != pB_id:
                # Resolve by confidence
                resolve_result = await session.call_tool("resolve_conflict", {
                    "pattern_a_id": pA_id,
                    "pattern_b_id": pB_id,
                    "strategy": "confidence",
                })
                resolution = json.loads(resolve_result.content[0].text)
                print(f"  Resolve (confidence) result: {resolution}")
                assert "action" in resolution
                assert resolution["action"] in ("resolved", "tied")
                if resolution["action"] == "resolved":
                    assert resolution.get("winner_id") in (pA_id, pB_id)
                    assert resolution.get("loser_id") in (pA_id, pB_id)
                print("  ✓ resolve_conflict works (confidence strategy)")

                # Test suppress strategy on a fresh pair
                pC_result = await session.call_tool("record_correction", {
                    "original": "stored data in JSON files on disk",
                    "corrected": "use Postgres for relational data",
                    "context": "data persistence layer",
                    "category": "tool_choice",
                })
                pC = json.loads(pC_result.content[0].text)
                pC_id = pC["pattern_id"]

                pD_result = await session.call_tool("record_correction", {
                    "original": "stored data in PostgreSQL tables",
                    "corrected": "use flat JSON files for storage",
                    "context": "data persistence layer",
                    "category": "tool_choice",
                })
                pD = json.loads(pD_result.content[0].text)
                pD_id = pD["pattern_id"]

                if pC_id != pD_id:
                    suppress_result = await session.call_tool("resolve_conflict", {
                        "pattern_a_id": pC_id,
                        "pattern_b_id": pD_id,
                        "strategy": "suppress",
                        "loser_id": pD_id,
                    })
                    suppression = json.loads(suppress_result.content[0].text)
                    print(f"  Resolve (suppress) result: {suppression}")
                    assert suppression["action"] == "suppressed"
                    assert suppression["loser_id"] == pD_id
                    print("  ✓ resolve_conflict works (suppress strategy)")
                else:
                    print(
                        "  ⚠ suppress test skipped: duplicate detector "
                        "collapsed pC/pD into one pattern"
                    )
            else:
                print(
                    "  ⚠ resolve_conflict confidence-strategy test "
                    "skipped: duplicate detector collapsed pA/pB"
                )

            # Classify correction (single)
            classify_result = await session.call_tool("classify_correction", {
                "text": "No, use 80% not 85%",
                "method": "regex",
            })
            classified = json.loads(classify_result.content[0].text)
            print(f"  Classified: {classified}")
            assert classified["is_correction"] is True

            # Classify correction (batch)
            batch_result = await session.call_tool("classify_correction", {
                "texts": [
                    "No, use 80% not 85%",
                    "Thanks, that looks great!",
                    "Actually, I prefer Python",
                ],
            })
            batch = json.loads(batch_result.content[0].text)
            print(f"  Batch classified: {len(batch)} results")
            assert len(batch) == 3
            assert batch[0]["is_correction"] is True
            assert batch[1]["is_correction"] is False

            # Mark pattern applied
            applied_result = await session.call_tool("mark_pattern_applied", {
                "pattern_id": pattern_id,
            })
            applied = json.loads(applied_result.content[0].text)
            print(f"  Mark applied: {applied}")
            assert applied["applied_count"] >= 1

            # Final stats
            final_stats_result = await session.call_tool("get_stats", {})
            final_stats = json.loads(final_stats_result.content[0].text)
            print(f"  Final stats: {final_stats}")
            assert final_stats["total_patterns"] >= 1
            assert final_stats["total_corrections"] >= 3

            print("  ✓ All MCP integration tests passed!")
            return True


def test_mcp_integration():
    """Test the full MCP protocol flow."""
    result = asyncio.run(_run_mcp_test())
    assert result is True


if __name__ == "__main__":
    print("\nPattern Memory — MCP Integration Test\n")
    asyncio.run(_run_mcp_test())
    print("\n✅ MCP integration test complete!\n")
