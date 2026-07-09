"""Mock tool layer for environment simulation.

Provides configurable mock tools that intercept agent tool calls
and return pre-defined responses. Supports latency simulation,
error injection, and call recording for behavioral assertions.

Also includes MockAPI (REST/GraphQL simulation) and MockDatabase
(in-memory data store with query interception) for richer
environment simulation beyond simple tool mocking.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class MockToolError(Exception):
    """Raised when a mock tool should simulate an error."""

    def __init__(self, message: str, status_code: int = 500):
        self.status_code = status_code
        super().__init__(message)


class RateLimitError(MockToolError):
    """Raised when a mock tool should simulate rate limiting."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: float = 60.0):
        self.retry_after = retry_after
        super().__init__(message, status_code=429)


class TimeoutError(MockToolError):
    """Raised when a mock tool should simulate a timeout."""

    def __init__(self, message: str = "Request timed out"):
        super().__init__(message, status_code=408)


__all__ = [
    # Errors
    "MockToolError",
    "RateLimitError",
    "TimeoutError",
    # Core types
    "MockToolCall",
    "MockTool",
    "MockAPI",
    "MockDatabase",
    # Builder
    "EnvironmentBuilder",
    "Environment",
]


@dataclass
class MockToolCall:
    """Record of a single call to a mock tool.

    Stored for later assertion and analysis.
    """
    tool_name: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class MockTool:
    """A configurable mock tool that intercepts calls and returns canned responses.

    Supports:
    - Static responses (same every time)
    - Dynamic responses (function-based)
    - Latency simulation
    - Error injection (one-shot or probability-based)
    - Call recording

    Usage:
        tool = MockTool("search", response={"results": [...]}, latency_ms=200)
        # or
        tool = MockTool("search", response_fn=lambda q: {"results": [q]})
        # or
        tool = MockTool("search", side_effect=RateLimitError())
    """
    name: str
    # Response configuration (exactly one required)
    response: Any = None
    response_fn: Callable[..., Any] | None = None
    side_effect: Exception | None = None
    # Latency simulation
    latency_ms: float = 0.0
    # Error injection (probability-based)
    error_probability: float = 0.0
    error_factory: Callable[[], Exception] | None = None
    # Optional per-instance call handler — when set, __call__ delegates
    # to this callable instead of the normal response/side_effect logic.
    # Used by sentinel.chaos ToolFailureInjector.wrap() to intercept calls.
    # Signature: handler(**kwargs) -> Any (may raise exceptions).
    call_handler: Callable[..., Any] | None = field(default=None, repr=False)
    # Call recording
    calls: list[MockToolCall] = field(default_factory=list, repr=False)

    def __call__(self, **kwargs: Any) -> Any:
        """Execute the mock tool with the given arguments.

        Records the call, simulates latency, and returns the configured response
        or raises the configured error.
        """
        # If a call handler is installed (e.g., by chaos injector), delegate to it.
        # The handler is responsible for its own recording if needed.
        if self.call_handler is not None:
            return self.call_handler(**kwargs)

        start = time.time()

        # Record the call
        call = MockToolCall(tool_name=self.name, arguments=kwargs)
        self.calls.append(call)

        # Simulate latency
        if self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000)

        # Check probability-based error injection
        if self.error_probability > 0:
            import random

            if random.random() < self.error_probability:
                error = (
                    self.error_factory()
                    if self.error_factory
                    else MockToolError("Injected error")
                )
                call.error = str(error)
                call.duration_ms = (time.time() - start) * 1000
                raise error

        # Raise configured side effect (one-shot)
        if self.side_effect is not None:
            error = self.side_effect
            self.side_effect = None  # Only fire once
            call.error = str(error)
            call.duration_ms = (time.time() - start) * 1000
            raise error

        # Return response
        if self.response_fn is not None:
            result = self.response_fn(**kwargs)
        elif self.response is not None:
            result = self.response
        else:
            result = None

        call.result = result
        call.duration_ms = (time.time() - start) * 1000
        return result

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_call(self) -> MockToolCall | None:
        return self.calls[-1] if self.calls else None


# ──────────────────────────────────────────────────────
# MockAPI — REST/GraphQL simulation
# ──────────────────────────────────────────────────────


@dataclass
class APICallRecord:
    """Record of a single API call to a MockAPI."""
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    response_status: int = 200
    response_body: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class RouteConfig:
    """Configuration for a single API route.

    Attributes:
        method: HTTP method (GET, POST, etc.) or "*" for any.
        url_pattern: URL pattern — exact string or regex (prefix with "~").
                     e.g. "/users/123" or "~^/users/\\d+$".
        status: HTTP status code to return.
        response: Response body (dict, list, string, etc.).
        headers: Response headers.
        latency_ms: Simulated response latency.
        error_probability: Probability of returning an error.
        error_status: Status code when error triggers (default 500).
    """
    method: str = "*"
    url_pattern: str = "*"
    status: int = 200
    response: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    latency_ms: float = 0.0
    error_probability: float = 0.0
    error_status: int = 500


class MockAPI:
    """Simulates a REST or GraphQL API with configurable routes.

    Supports:
    - Route matching by method + URL pattern (exact or regex)
    - Configurable response status codes and bodies
    - Latency simulation per route
    - Error injection (probability-based)
    - Rate limiting (per-IP or global)
    - Call recording for behavioral assertions
    - GraphQL query parsing (simplified)

    Usage:
        api = MockAPI(base_url="https://api.example.com")
        api.add_route(RouteConfig(
            method="GET",
            url_pattern="/users",
            response={"users": [...]},
            latency_ms=50,
        ))
        api.add_route(RouteConfig(
            method="POST",
            url_pattern="/users",
            status=201,
            response={"created": True},
        ))

        # Simulate calls
        result = api.request("GET", "/users")
        assert result == {"users": [...]}

        # Or as a tool-compatible callable
        tool = api.as_tool("api_call")
        result = tool(method="GET", url="/users")
    """

    def __init__(
        self,
        base_url: str = "",
        rate_limit_per_minute: int = 0,
        default_status: int = 200,
        default_response: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.rate_limit_per_minute = rate_limit_per_minute
        self.default_status = default_status
        self.default_response = default_response

        self._routes: list[RouteConfig] = []
        self._calls: list[APICallRecord] = []
        self._call_timestamps: list[float] = []
        self._graphql_handlers: dict[str, Callable] = {}

    def add_route(self, route: RouteConfig) -> MockAPI:
        """Add a route configuration. Returns self for chaining."""
        self._routes.append(route)
        return self

    def graphql_handler(
        self,
        operation_name: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> MockAPI:
        """Register a handler for a specific GraphQL operation.

        Args:
            operation_name: The GraphQL operation/mutation name.
            handler: Callable that receives the variables dict and returns
                     the response data.
        """
        self._graphql_handlers[operation_name] = handler
        return self

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: Any = None,
    ) -> Any:
        """Execute a mock API request.

        Matches the request against registered routes and returns the
        configured response. Raises MockToolError if no route matches.

        Returns:
            The response body from the matching route.

        Raises:
            MockToolError: If no route matches or error injection triggers.
            RateLimitError: If rate limit is exceeded.
        """
        start = time.time()
        headers = headers or {}

        # Rate limit check
        if self.rate_limit_per_minute > 0:
            now = time.time()
            # Prune timestamps older than 60 seconds
            self._call_timestamps = [
                t for t in self._call_timestamps if now - t < 60
            ]
            if len(self._call_timestamps) >= self.rate_limit_per_minute:
                error = RateLimitError(
                    f"API rate limit exceeded: {self.rate_limit_per_minute}/min"
                )
                record = APICallRecord(
                    method=method,
                    url=url,
                    headers=headers,
                    body=body,
                    error=str(error),
                    duration_ms=(time.time() - start) * 1000,
                )
                self._calls.append(record)
                raise error
            self._call_timestamps.append(now)

        # Find matching route
        route = self._match_route(method, url)

        # Apply latency
        if route and route.latency_ms > 0:
            time.sleep(route.latency_ms / 1000)

        # Check error injection
        if route and route.error_probability > 0:
            import random
            if random.random() < route.error_probability:
                status = route.error_status
                error = MockToolError(
                    f"API error: {status} on {method} {url}",
                    status_code=status,
                )
                record = APICallRecord(
                    method=method,
                    url=url,
                    headers=headers,
                    body=body,
                    response_status=status,
                    error=str(error),
                    duration_ms=(time.time() - start) * 1000,
                )
                self._calls.append(record)
                raise error

        # Return response
        if route is not None:
            status = route.status
            response = route.response
        else:
            status = self.default_status
            response = self.default_response

        record = APICallRecord(
            method=method,
            url=url,
            headers=headers,
            body=body,
            response_status=status,
            response_body=response,
            duration_ms=(time.time() - start) * 1000,
        )
        self._calls.append(record)

        if response is None and status == 200:
            # No matching route and no default — this is an error
            raise MockToolError(
                f"No route matched: {method} {url}",
                status_code=404,
            )

        return response

    def graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> Any:
        """Execute a mock GraphQL query/mutation.

        Parses the operation name from the query (if not provided) and
        routes to the registered handler.

        Returns:
            The response data from the registered handler.

        Raises:
            MockToolError: If no handler is registered for the operation.
        """
        # Extract operation name from query if not provided
        if operation_name is None:
            operation_name = self._extract_operation(query)

        if operation_name not in self._graphql_handlers:
            raise MockToolError(
                f"No handler registered for GraphQL operation: {operation_name}",
                status_code=400,
            )

        handler = self._graphql_handlers[operation_name]
        return handler(variables or {})

    def _match_route(self, method: str, url: str) -> RouteConfig | None:
        """Find the first route matching the method and URL."""
        # Strip base URL if present
        if self.base_url and url.startswith(self.base_url):
            url = url[len(self.base_url):]
        if not url.startswith("/"):
            url = "/" + url

        for route in self._routes:
            # Method match
            if route.method != "*" and route.method.upper() != method.upper():
                continue
            # URL match (exact or regex)
            if route.url_pattern == "*":
                return route
            if route.url_pattern.startswith("~"):
                # Regex pattern
                pattern = route.url_pattern[1:]
                if re.match(pattern, url):
                    return route
            else:
                if route.url_pattern == url:
                    return route

        return None

    def _extract_operation(self, query: str) -> str:
        """Extract the operation name from a GraphQL query string."""
        # Try: query/operation Name {
        match = re.search(
            r"(?:query|mutation|subscription)\s+(\w+)", query
        )
        if match:
            return match.group(1)
        # Fallback: first word after opening brace... just use "default"
        return "default"

    @property
    def call_count(self) -> int:
        return len(self._calls)

    @property
    def calls(self) -> list[APICallRecord]:
        return list(self._calls)

    @property
    def last_call(self) -> APICallRecord | None:
        return self._calls[-1] if self._calls else None

    def reset(self) -> None:
        """Clear all recorded calls."""
        self._calls.clear()
        self._call_timestamps.clear()

    def as_tool(self, name: str = "api_call") -> MockTool:
        """Create a MockTool that delegates to this API.

        The tool accepts method, url, headers, and body kwargs and
        routes them through MockAPI.request().

        Useful for wiring MockAPI into the environment as a tool.
        """
        def _handler(**kwargs: Any) -> Any:
            return self.request(
                method=kwargs.get("method", "GET"),
                url=kwargs.get("url", "/"),
                headers=kwargs.get("headers", {}),
                body=kwargs.get("body"),
            )

        return MockTool(name=name, response_fn=_handler)


# ──────────────────────────────────────────────────────
# MockDatabase — in-memory data store with query interception
# ──────────────────────────────────────────────────────


@dataclass
class QueryRecord:
    """Record of a single database query."""
    query_type: str  # "select", "insert", "update", "delete"
    table: str
    query: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    row_count: int = 0
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


class MockDatabase:
    """In-memory data store with query interception.

    Simulates a database with tables, rows, and basic query support.
    Supports:
    - Table creation and row insertion
    - SELECT with simple WHERE clause matching
    - UPDATE and DELETE operations
    - Query recording for behavioral assertions
    - Latency simulation
    - Error injection

    Usage:
        db = MockDatabase()
        db.create_table("users", schema={"id": "int", "name": "str", "email": "str"})
        db.insert("users", {"id": 1, "name": "Alice", "email": "alice@example.com"})
        db.insert("users", {"id": 2, "name": "Bob", "email": "bob@example.com"})

        results = db.select("users", where={"name": "Alice"})
        assert results == [{"id": 1, "name": "Alice", "email": "alice@example.com"}]

        # Or as a tool-compatible callable
        tool = db.as_tool("database")
        results = tool(table="users", operation="select", where={"name": "Alice"})
    """

    def __init__(
        self,
        latency_ms: float = 0.0,
        error_probability: float = 0.0,
    ) -> None:
        self.latency_ms = latency_ms
        self.error_probability = error_probability

        self._tables: dict[str, list[dict[str, Any]]] = {}
        self._schemas: dict[str, dict[str, str]] = {}
        self._queries: list[QueryRecord] = []

    def create_table(
        self,
        name: str,
        schema: dict[str, str] | None = None,
    ) -> None:
        """Create a table with an optional schema definition.

        Args:
            name: Table name.
            schema: Optional column definitions {column_name: type_str}.
                    Types are informational only — MockDatabase is schemaless.
        """
        if name not in self._tables:
            self._tables[name] = []
            self._schemas[name] = schema or {}

    def drop_table(self, name: str) -> None:
        """Drop a table and all its data."""
        self._tables.pop(name, None)
        self._schemas.pop(name, None)

    def insert(self, table: str, row: dict[str, Any]) -> None:
        """Insert a row into a table.

        Args:
            table: Table name (created automatically if it doesn't exist).
            row: Row data as a dictionary.

        Raises:
            MockToolError: If error injection triggers.
        """
        self._simulate_delay()
        self._check_error("insert", table)

        if table not in self._tables:
            self.create_table(table)

        record = QueryRecord(
            query_type="insert",
            table=table,
            query=f"INSERT INTO {table}",
            parameters=row,
            row_count=1,
        )

        self._tables[table].append(dict(row))
        record.duration_ms = self.latency_ms
        self._queries.append(record)

    def insert_many(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Insert multiple rows into a table.

        Returns the number of rows inserted.
        """
        for row in rows:
            self.insert(table, row)
        return len(rows)

    def select(
        self,
        table: str,
        where: dict[str, Any] | None = None,
        columns: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Select rows from a table with optional filtering.

        Args:
            table: Table name.
            where: Simple equality filter {column: value}. All conditions
                   must match (AND logic).
            columns: Optional list of columns to return. If None, returns all.
            limit: Maximum rows to return.

        Returns:
            List of matching row dicts.

        Raises:
            MockToolError: If table doesn't exist or error injection triggers.
        """
        self._simulate_delay()
        self._check_error("select", table)

        if table not in self._tables:
            raise MockToolError(f"Table '{table}' does not exist", status_code=404)

        rows = self._tables[table]

        # Apply WHERE filter
        if where:
            rows = [
                row for row in rows
                if all(row.get(k) == v for k, v in where.items())
            ]

        # Apply column selection
        if columns:
            rows = [{k: row.get(k) for k in columns} for row in rows]

        # Apply limit
        if limit is not None:
            rows = rows[:limit]

        record = QueryRecord(
            query_type="select",
            table=table,
            query=f"SELECT FROM {table}",
            parameters=where or {},
            result=rows,
            row_count=len(rows),
        )
        self._queries.append(record)

        return [dict(row) for row in rows]  # Return copies

    def update(
        self,
        table: str,
        updates: dict[str, Any],
        where: dict[str, Any] | None = None,
    ) -> int:
        """Update rows in a table.

        Returns the number of rows updated.
        """
        self._simulate_delay()
        self._check_error("update", table)

        if table not in self._tables:
            raise MockToolError(f"Table '{table}' does not exist", status_code=404)

        count = 0
        for row in self._tables[table]:
            if where and not all(row.get(k) == v for k, v in where.items()):
                continue
            row.update(updates)
            count += 1

        record = QueryRecord(
            query_type="update",
            table=table,
            query=f"UPDATE {table}",
            parameters={"updates": updates, "where": where},
            row_count=count,
        )
        self._queries.append(record)

        return count

    def delete(
        self,
        table: str,
        where: dict[str, Any] | None = None,
    ) -> int:
        """Delete rows from a table.

        Returns the number of rows deleted.
        """
        self._simulate_delay()
        self._check_error("delete", table)

        if table not in self._tables:
            raise MockToolError(f"Table '{table}' does not exist", status_code=404)

        original_len = len(self._tables[table])
        if where:
            self._tables[table] = [
                row for row in self._tables[table]
                if not all(row.get(k) == v for k, v in where.items())
            ]
        else:
            self._tables[table] = []

        count = original_len - len(self._tables[table])

        record = QueryRecord(
            query_type="delete",
            table=table,
            query=f"DELETE FROM {table}",
            parameters={"where": where},
            row_count=count,
        )
        self._queries.append(record)

        return count

    def count(self, table: str, where: dict[str, Any] | None = None) -> int:
        """Count rows in a table with optional filtering."""
        results = self.select(table, where=where)
        return len(results)

    def get_table(self, name: str) -> list[dict[str, Any]]:
        """Get all rows in a table (for test setup/verification)."""
        return [dict(row) for row in self._tables.get(name, [])]

    def get_tables(self) -> dict[str, list[dict[str, Any]]]:
        """Get all tables and their rows."""
        return {name: [dict(row) for row in rows] for name, rows in self._tables.items()}

    @property
    def query_count(self) -> int:
        return len(self._queries)

    @property
    def queries(self) -> list[QueryRecord]:
        return list(self._queries)

    @property
    def last_query(self) -> QueryRecord | None:
        return self._queries[-1] if self._queries else None

    def queries_by_type(self, query_type: str) -> list[QueryRecord]:
        """Get all queries of a specific type (select, insert, update, delete)."""
        return [q for q in self._queries if q.query_type == query_type]

    def queries_on_table(self, table: str) -> list[QueryRecord]:
        """Get all queries on a specific table."""
        return [q for q in self._queries if q.table == table]

    def reset(self) -> None:
        """Clear all data and query history."""
        self._tables.clear()
        self._schemas.clear()
        self._queries.clear()

    def reset_queries(self) -> None:
        """Clear query history only (keep data)."""
        self._queries.clear()

    def _simulate_delay(self) -> None:
        """Simulate query latency."""
        if self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000)

    def _check_error(self, operation: str, table: str) -> None:
        """Check if error injection should trigger."""
        if self.error_probability > 0:
            import random
            if random.random() < self.error_probability:
                raise MockToolError(
                    f"Database error during {operation} on '{table}'",
                    status_code=500,
                )

    def as_tool(self, name: str = "database") -> MockTool:
        """Create a MockTool that delegates to this database.

        The tool accepts table, operation, where, data, and columns kwargs.

        Supported operations: select, insert, update, delete, count, list_tables.
        """
        def _handler(**kwargs: Any) -> Any:
            operation = kwargs.get("operation", "select")
            table = kwargs.get("table", "")

            if operation == "select":
                return self.select(
                    table=table,
                    where=kwargs.get("where"),
                    columns=kwargs.get("columns"),
                    limit=kwargs.get("limit"),
                )
            elif operation == "insert":
                data = kwargs.get("data", {})
                self.insert(table=table, row=data)
                return {"inserted": True}
            elif operation == "insert_many":
                data = kwargs.get("data", [])
                count = self.insert_many(table=table, rows=data)
                return {"inserted": count}
            elif operation == "update":
                count = self.update(
                    table=table,
                    updates=kwargs.get("updates", {}),
                    where=kwargs.get("where"),
                )
                return {"updated": count}
            elif operation == "delete":
                count = self.delete(
                    table=table,
                    where=kwargs.get("where"),
                )
                return {"deleted": count}
            elif operation == "count":
                return {"count": self.count(
                    table=table,
                    where=kwargs.get("where"),
                )}
            elif operation == "list_tables":
                return {"tables": list(self._tables.keys())}
            else:
                raise MockToolError(f"Unknown operation: {operation}")

        return MockTool(name=name, response_fn=_handler)


# ──────────────────────────────────────────────────────
# EnvironmentBuilder — fluent API
# ──────────────────────────────────────────────────────


class EnvironmentBuilder:
    """Fluent API for composing test environments with mock tools.

    Supports:
    - mock_tool() — add a mock tool
    - mock_api() — add a mock REST/GraphQL API
    - mock_database() — add a mock database
    - with_rate_limit() — set global rate limit
    - build() — construct the Environment

    Usage:
        env = (EnvironmentBuilder()
            .mock_tool("search", response=SEARCH_RESULTS)
            .mock_tool("send_email", side_effect=RateLimitError())
            .mock_api("https://api.example.com")
            .mock_database("users_db")
            .with_rate_limit(calls_per_minute=10)
            .build())
    """

    def __init__(self) -> None:
        self._tools: dict[str, MockTool] = {}
        self._apis: dict[str, MockAPI] = {}
        self._databases: dict[str, MockDatabase] = {}
        self._rate_limit: dict[str, Any] | None = None

    def mock_tool(
        self,
        name: str,
        response: Any = None,
        response_fn: Callable | None = None,
        side_effect: Exception | None = None,
        latency_ms: float = 0.0,
        error_probability: float = 0.0,
    ) -> EnvironmentBuilder:
        """Add a mock tool to the environment."""
        self._tools[name] = MockTool(
            name=name,
            response=response,
            response_fn=response_fn,
            side_effect=side_effect,
            latency_ms=latency_ms,
            error_probability=error_probability,
        )
        return self

    def mock_api(
        self,
        base_url: str = "",
        name: str | None = None,
        rate_limit_per_minute: int = 0,
        default_status: int = 200,
        default_response: Any = None,
    ) -> EnvironmentBuilder:
        """Add a mock REST/GraphQL API to the environment.

        Args:
            base_url: Base URL for the API (e.g. "https://api.example.com").
            name: Tool name for the API. Defaults to derived name from URL.
            rate_limit_per_minute: Global rate limit (0 = unlimited).
            default_status: Default HTTP status for unmatched routes.
            default_response: Default response body for unmatched routes.

        Returns:
            self, for chaining. Access the API via env.get_api(name) or
            env.get_tool(name) (it's registered as a tool too).
        """
        api_name = name or self._derive_api_name(base_url)
        api = MockAPI(
            base_url=base_url,
            rate_limit_per_minute=rate_limit_per_minute,
            default_status=default_status,
            default_response=default_response,
        )
        self._apis[api_name] = api

        # Also register as a tool so it can be called via the environment
        self._tools[api_name] = api.as_tool(name=api_name)

        return self

    def mock_database(
        self,
        name: str = "database",
        latency_ms: float = 0.0,
        error_probability: float = 0.0,
    ) -> EnvironmentBuilder:
        """Add a mock database to the environment.

        Args:
            name: Tool name for the database.
            latency_ms: Simulated query latency.
            error_probability: Probability of random errors.

        Returns:
            self, for chaining. Access via env.get_database(name) or
            env.get_tool(name) (it's registered as a tool too).
        """
        db = MockDatabase(
            latency_ms=latency_ms,
            error_probability=error_probability,
        )
        self._databases[name] = db

        # Also register as a tool so it can be called via the environment
        self._tools[name] = db.as_tool(name=name)

        return self

    def with_rate_limit(self, calls_per_minute: int = 10) -> EnvironmentBuilder:
        """Set a global rate limit for all tools."""
        self._rate_limit = {"calls_per_minute": calls_per_minute}
        return self

    def build(self) -> Environment:
        """Build the configured environment."""
        return Environment(
            tools=self._tools,
            apis=self._apis,
            databases=self._databases,
            rate_limit=self._rate_limit,
        )

    @staticmethod
    def _derive_api_name(base_url: str) -> str:
        """Derive a tool name from a base URL.

        E.g. "https://api.example.com" → "api_example_com"
        """
        if not base_url:
            return "api"
        # Strip protocol
        name = re.sub(r"^https?://", "", base_url)
        # Strip trailing path
        name = name.split("/")[0]
        # Replace dots and dashes with underscores
        name = re.sub(r"[.\-]", "_", name)
        # Remove any remaining non-alphanumeric except underscore
        name = re.sub(r"[^a-zA-Z0-9_]", "", name)
        return name or "api"


# ──────────────────────────────────────────────────────
# Environment — composed test environment
# ──────────────────────────────────────────────────────


@dataclass
class Environment:
    """A composed test environment with mock tools, APIs, and databases.

    Provides tools by name and tracks all calls made
    across the entire environment.
    """
    tools: dict[str, MockTool] = field(default_factory=dict)
    apis: dict[str, MockAPI] = field(default_factory=dict)
    databases: dict[str, MockDatabase] = field(default_factory=dict)
    rate_limit: dict[str, Any] | None = None

    def get_tool(self, name: str) -> MockTool | None:
        """Retrieve a mock tool by name."""
        return self.tools.get(name)

    def get_tools(self) -> dict[str, MockTool]:
        """Get all mock tools."""
        return self.tools

    def get_api(self, name: str) -> MockAPI | None:
        """Retrieve a mock API by name."""
        return self.apis.get(name)

    def get_apis(self) -> dict[str, MockAPI]:
        """Get all mock APIs."""
        return self.apis

    def get_database(self, name: str) -> MockDatabase | None:
        """Retrieve a mock database by name."""
        return self.databases.get(name)

    def get_databases(self) -> dict[str, MockDatabase]:
        """Get all mock databases."""
        return self.databases

    @property
    def all_calls(self) -> list[MockToolCall]:
        """Get all tool calls across all tools, in chronological order."""
        calls = []
        for tool in self.tools.values():
            calls.extend(tool.calls)
        return sorted(calls, key=lambda c: c.timestamp)

    def reset(self) -> None:
        """Clear all recorded calls."""
        for tool in self.tools.values():
            tool.calls.clear()
        for api in self.apis.values():
            api.reset()
        for db in self.databases.values():
            db.reset_queries()
