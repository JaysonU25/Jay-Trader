from fastapi import HTTPException


def not_found(resource: str, identifier: str) -> HTTPException:
    """One error body shape across every route."""
    return HTTPException(
        status_code=404,
        detail={"error": "not_found", "resource": resource, "id": identifier},
    )
