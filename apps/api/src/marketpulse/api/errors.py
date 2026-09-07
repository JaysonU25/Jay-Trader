from fastapi import HTTPException


def not_found(resource: str, identifier: str) -> HTTPException:
    """One error body shape across every route."""
    return HTTPException(
        status_code=404,
        detail={"error": "not_found", "resource": resource, "id": identifier},
    )


NOT_FOUND_RESPONSE = {
    404: {
        "description": "The requested resource is not tracked.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {"error": "not_found", "resource": "symbol", "id": "ZZZZ"}
                }
            }
        },
    }
}

UNAUTHORIZED_RESPONSE = {
    401: {
        "description": "Missing or invalid request signature.",
        "content": {
            "application/json": {"example": {"detail": "unauthorized"}}
        },
    }
}
