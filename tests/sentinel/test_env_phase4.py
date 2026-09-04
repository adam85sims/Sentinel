"""Tests for MockAPI and MockDatabase (Phase 4 env extensions)."""

import pytest

from sentinel.env import (
    EnvironmentBuilder,
    MockAPI,
    MockDatabase,
    MockTool,
    MockToolError,
    RateLimitError,
    RouteConfig,
)

# ──────────────────────────────────────────────────────
# MockAPI
# ──────────────────────────────────────────────────────


class TestMockAPI:
    def test_basic_route_matching(self):
        """API matches routes by method and URL."""
        api = MockAPI()
        api.add_route(RouteConfig(
            method="GET",
            url_pattern="/users",
            response={"users": ["alice", "bob"]},
        ))

        result = api.request("GET", "/users")
        assert result == {"users": ["alice", "bob"]}

    def test_method_mismatch(self):
        """API returns error on method mismatch (no matching route)."""
        api = MockAPI()
        api.add_route(RouteConfig(method="GET", url_pattern="/users", response=[]))

        with pytest.raises(MockToolError, match="No route matched"):
            api.request("POST", "/users")

    def test_regex_url_pattern(self):
        """API supports regex URL patterns."""
        api = MockAPI()
        api.add_route(RouteConfig(
            url_pattern="~^/users/\\d+$",
            response={"found": True},
        ))

        assert api.request("GET", "/users/123") == {"found": True}
        assert api.request("GET", "/users/456") == {"found": True}

    def test_wildcard_method(self):
        """Wildcard method matches any HTTP method."""
        api = MockAPI()
        api.add_route(RouteConfig(method="*", url_pattern="/health", response="ok"))

        assert api.request("GET", "/health") == "ok"
        assert api.request("POST", "/health") == "ok"
        assert api.request("DELETE", "/health") == "ok"

    def test_wildcard_url(self):
        """Wildcard URL pattern matches everything."""
        api = MockAPI(default_response="fallback")
        api.add_route(RouteConfig(response="catch-all"))

        assert api.request("GET", "/anything") == "catch-all"

    def test_latency_simulation(self):
        """API simulates latency per route."""
        api = MockAPI()
        api.add_route(RouteConfig(
            url_pattern="/slow",
            response="data",
            latency_ms=10,  # Small but non-zero
        ))

        result = api.request("GET", "/slow")
        assert result == "data"

    def test_error_injection(self):
        """API injects errors based on probability."""
        api = MockAPI()
        api.add_route(RouteConfig(
            url_pattern="/flaky",
            response="ok",
            error_probability=1.0,  # Always error
            error_status=503,
        ))

        with pytest.raises(MockToolError, match="503"):
            api.request("GET", "/flaky")

    def test_rate_limiting(self):
        """API enforces rate limits."""
        api = MockAPI(rate_limit_per_minute=2)
        api.add_route(RouteConfig(response="ok"))

        # First two calls succeed
        api.request("GET", "/test")
        api.request("GET", "/test")

        # Third call triggers rate limit
        with pytest.raises(RateLimitError):
            api.request("GET", "/test")

    def test_call_recording(self):
        """API records all calls."""
        api = MockAPI()
        api.add_route(RouteConfig(response="ok"))

        api.request("GET", "/a")
        api.request("POST", "/b", body={"data": 1})

        assert api.call_count == 2
        assert api.calls[0].method == "GET"
        assert api.calls[0].url == "/a"
        assert api.calls[1].body == {"data": 1}

    def test_base_url_stripping(self):
        """API strips base URL before matching."""
        api = MockAPI(base_url="https://api.example.com")
        api.add_route(RouteConfig(url_pattern="/users", response=[1, 2, 3]))

        result = api.request("GET", "https://api.example.com/users")
        assert result == [1, 2, 3]

    def test_reset(self):
        """reset clears call history."""
        api = MockAPI()
        api.add_route(RouteConfig(response="ok"))
        api.request("GET", "/x")

        assert api.call_count == 1
        api.reset()
        assert api.call_count == 0

    def test_as_tool(self):
        """as_tool creates a MockTool that delegates to the API."""
        api = MockAPI()
        api.add_route(RouteConfig(
            method="GET",
            url_pattern="/data",
            response={"key": "value"},
        ))

        tool = api.as_tool(name="my_api")
        assert isinstance(tool, MockTool)
        assert tool.name == "my_api"

        result = tool(method="GET", url="/data")
        assert result == {"key": "value"}
        assert tool.call_count == 1

    def test_chaining(self):
        """add_route returns self for chaining."""
        api = MockAPI()
        result = (
            api
            .add_route(RouteConfig(url_pattern="/a", response=1))
            .add_route(RouteConfig(url_pattern="/b", response=2))
        )
        assert result is api
        assert api.call_count == 0


class TestMockAPIGraphQL:
    def test_graphql_handler(self):
        """GraphQL handler routes by operation name."""
        api = MockAPI()
        api.graphql_handler("GetUser", lambda vars: {"user": vars.get("id")})

        result = api.graphql(
            query="query GetUser($id: ID!) { user(id: $id) { name } }",
            variables={"id": "123"},
        )
        assert result == {"user": "123"}

    def test_graphql_operation_name_from_query(self):
        """GraphQL extracts operation name from query string."""
        api = MockAPI()
        api.graphql_handler("CreateUser", lambda vars: {"created": True})

        result = api.graphql(query="mutation CreateUser { createUser { id } }")
        assert result == {"created": True}

    def test_graphql_no_handler(self):
        """GraphQL raises error for unknown operation."""
        api = MockAPI()

        with pytest.raises(MockToolError, match="No handler"):
            api.graphql(query="query Unknown { ... }")

    def test_graphql_explicit_operation_name(self):
        """GraphQL accepts explicit operation name."""
        api = MockAPI()
        api.graphql_handler("Op1", lambda v: "first")
        api.graphql_handler("Op2", lambda v: "second")

        result = api.graphql(query="query Op2 { ... }", operation_name="Op2")
        assert result == "second"


# ──────────────────────────────────────────────────────
# MockDatabase
# ──────────────────────────────────────────────────────


class TestMockDatabase:
    def test_create_table_and_insert(self):
        """Can create table and insert rows."""
        db = MockDatabase()
        db.create_table("users")
        db.insert("users", {"id": 1, "name": "Alice"})
        db.insert("users", {"id": 2, "name": "Bob"})

        assert db.count("users") == 2

    def test_insert_auto_creates_table(self):
        """Insert auto-creates table if it doesn't exist."""
        db = MockDatabase()
        db.insert("auto_table", {"x": 1})

        assert db.count("auto_table") == 1

    def test_select_with_where(self):
        """Select with WHERE filter."""
        db = MockDatabase()
        db.insert("users", {"id": 1, "name": "Alice"})
        db.insert("users", {"id": 2, "name": "Bob"})
        db.insert("users", {"id": 3, "name": "Alice"})

        results = db.select("users", where={"name": "Alice"})
        assert len(results) == 2
        assert all(r["name"] == "Alice" for r in results)

    def test_select_with_columns(self):
        """Select with column projection."""
        db = MockDatabase()
        db.insert("users", {"id": 1, "name": "Alice", "email": "a@b.com"})

        results = db.select("users", columns=["name"])
        assert results == [{"name": "Alice"}]

    def test_select_with_limit(self):
        """Select with row limit."""
        db = MockDatabase()
        for i in range(10):
            db.insert("items", {"id": i})

        results = db.select("users" if False else "items", limit=3)
        assert len(results) == 3

    def test_select_nonexistent_table(self):
        """Select on non-existent table raises error."""
        db = MockDatabase()

        with pytest.raises(MockToolError, match="does not exist"):
            db.select("ghost_table")

    def test_update(self):
        """Update modifies matching rows."""
        db = MockDatabase()
        db.insert("users", {"id": 1, "name": "Alice", "active": True})
        db.insert("users", {"id": 2, "name": "Bob", "active": True})

        count = db.update("users", {"active": False}, where={"name": "Bob"})
        assert count == 1

        results = db.select("users", where={"name": "Bob"})
        assert results[0]["active"] is False

    def test_delete(self):
        """Delete removes matching rows."""
        db = MockDatabase()
        db.insert("users", {"id": 1, "name": "Alice"})
        db.insert("users", {"id": 2, "name": "Bob"})

        count = db.delete("users", where={"name": "Alice"})
        assert count == 1
        assert db.count("users") == 1

    def test_delete_all(self):
        """Delete without WHERE removes all rows."""
        db = MockDatabase()
        db.insert("users", {"id": 1})
        db.insert("users", {"id": 2})

        count = db.delete("users")
        assert count == 2
        assert db.count("users") == 0

    def test_insert_many(self):
        """insert_many inserts multiple rows."""
        db = MockDatabase()
        count = db.insert_many("items", [{"id": i} for i in range(5)])
        assert count == 5
        assert db.count("items") == 5

    def test_query_recording(self):
        """Database records all queries."""
        db = MockDatabase()
        db.insert("t", {"x": 1})
        db.select("t")
        db.update("t", {"x": 2})
        db.delete("t")

        assert db.query_count == 4
        assert db.queries[0].query_type == "insert"
        assert db.queries[1].query_type == "select"
        assert db.queries[2].query_type == "update"
        assert db.queries[3].query_type == "delete"

    def test_queries_by_type(self):
        """queries_by_type filters correctly."""
        db = MockDatabase()
        db.insert("t", {"x": 1})
        db.insert("t", {"x": 2})
        db.select("t")

        inserts = db.queries_by_type("insert")
        assert len(inserts) == 2
        selects = db.queries_by_type("select")
        assert len(selects) == 1

    def test_queries_on_table(self):
        """queries_on_table filters correctly."""
        db = MockDatabase()
        db.insert("a", {"x": 1})
        db.insert("b", {"y": 2})
        db.select("a")

        a_queries = db.queries_on_table("a")
        assert len(a_queries) == 2

    def test_error_injection(self):
        """Database injects errors based on probability."""
        db = MockDatabase(error_probability=1.0)
        db.create_table("t")

        with pytest.raises(MockToolError, match="Database error"):
            db.select("t")

    def test_drop_table(self):
        """drop_table removes table and schema."""
        db = MockDatabase()
        db.create_table("temp", schema={"id": "int"})
        db.insert("temp", {"id": 1})
        db.drop_table("temp")

        assert "temp" not in db.get_tables()

    def test_reset(self):
        """reset clears all data and queries."""
        db = MockDatabase()
        db.insert("t", {"x": 1})
        db.select("t")

        db.reset()
        assert db.get_tables() == {}
        assert db.query_count == 0

    def test_reset_queries(self):
        """reset_queries clears queries but keeps data."""
        db = MockDatabase()
        db.insert("t", {"x": 1})

        db.reset_queries()
        assert db.query_count == 0
        assert db.count("t") == 1

    def test_as_tool(self):
        """as_tool creates a MockTool that delegates to the database."""
        db = MockDatabase()
        tool = db.as_tool(name="mydb")
        assert isinstance(tool, MockTool)
        assert tool.name == "mydb"

        # Use tool to insert
        tool(table="users", operation="insert", data={"id": 1, "name": "Test"})
        assert db.count("users") == 1

        # Use tool to select
        results = tool(table="users", operation="select")
        assert results == [{"id": 1, "name": "Test"}]

        # Use tool to count
        result = tool(table="users", operation="count")
        assert result == {"count": 1}

    def test_as_tool_list_tables(self):
        """as_tool supports list_tables operation."""
        db = MockDatabase()
        db.insert("a", {"x": 1})
        db.insert("b", {"y": 2})
        tool = db.as_tool()

        result = tool(operation="list_tables")
        assert sorted(result["tables"]) == ["a", "b"]

    def test_as_tool_unknown_operation(self):
        """as_tool raises error for unknown operation."""
        db = MockDatabase()
        tool = db.as_tool()

        with pytest.raises(MockToolError, match="Unknown operation"):
            tool(operation="banana")


# ──────────────────────────────────────────────────────
# EnvironmentBuilder extensions
# ──────────────────────────────────────────────────────


class TestEnvironmentBuilderExtensions:
    def test_mock_api_in_builder(self):
        """mock_api adds API and registers as tool."""
        env = (
            EnvironmentBuilder()
            .mock_api(base_url="https://api.test.com", name="test_api")
            .build()
        )

        assert env.get_api("test_api") is not None
        assert env.get_tool("test_api") is not None

    def test_mock_database_in_builder(self):
        """mock_database adds database and registers as tool."""
        env = (
            EnvironmentBuilder()
            .mock_database(name="mydb")
            .build()
        )

        assert env.get_database("mydb") is not None
        assert env.get_tool("mydb") is not None

    def test_mock_api_auto_name(self):
        """mock_api derives name from URL when not specified."""
        env = (
            EnvironmentBuilder()
            .mock_api(base_url="https://api.example.com")
            .build()
        )

        assert env.get_api("api_example_com") is not None

    def test_derive_api_name(self):
        """_derive_api_name handles various URL formats."""
        assert EnvironmentBuilder._derive_api_name("https://api.example.com") == "api_example_com"
        assert EnvironmentBuilder._derive_api_name("https://foo-bar.baz.io") == "foo_bar_baz_io"
        assert EnvironmentBuilder._derive_api_name("") == "api"
        assert EnvironmentBuilder._derive_api_name("https://api.test.com/v1") == "api_test_com"

    def test_combined_env(self):
        """Full environment with tools, API, and database."""
        env = (
            EnvironmentBuilder()
            .mock_tool("search", response="results")
            .mock_api(base_url="https://api.test.com", name="test_api")
            .mock_database(name="db")
            .build()
        )

        assert env.get_tool("search") is not None
        assert env.get_api("test_api") is not None
        assert env.get_database("db") is not None
        assert len(env.get_tools()) == 3  # search + test_api + db

    def test_reset_clears_apis_and_databases(self):
        """Environment.reset() clears API and DB call history."""
        env = (
            EnvironmentBuilder()
            .mock_api(name="api")
            .mock_database(name="db")
            .build()
        )

        # Make some calls
        env.get_api("api").add_route(RouteConfig(response="ok"))
        env.get_api("api").request("GET", "/test")
        env.get_database("db").insert("t", {"x": 1})

        env.reset()

        assert env.get_api("api").call_count == 0
        assert env.get_database("db").query_count == 0
