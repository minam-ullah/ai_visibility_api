from flask import jsonify


class APIError(Exception):
    """Raised for any expected, client-facing error. Carries an HTTP status
    code and a machine-readable error code so every endpoint returns errors
    in the same shape:

        {"error": {"code": "NOT_FOUND", "message": "..."}}
    """

    def __init__(self, message: str, status_code: int = 400, code: str = "BAD_REQUEST"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code

    def to_response(self):
        return jsonify({"error": {"code": self.code, "message": self.message}}), self.status_code


def register_error_handlers(app):
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return err.to_response()

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Resource not found"}}), 404

    @app.errorhandler(405)
    def handle_405(err):
        return jsonify({"error": {"code": "METHOD_NOT_ALLOWED", "message": str(err)}}), 405

    @app.errorhandler(500)
    def handle_500(err):
        app.logger.exception("Unhandled server error")
        return jsonify({"error": {"code": "INTERNAL_ERROR", "message": "Something went wrong"}}), 500
