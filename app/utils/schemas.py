"""Request-body validation schemas.

Using marshmallow here instead of hand-rolled `if not body.get(...)` checks
gets us: type coercion/checking (not just presence), field-level error
messages, and one consistent place to see exactly what shape the API
accepts -- rather than that logic being scattered across route handlers.
"""
from marshmallow import Schema, fields, validate, ValidationError, EXCLUDE

__all__ = ["CreateProfileSchema", "ValidationError"]


class CreateProfileSchema(Schema):
    class Meta:
        unknown = EXCLUDE  # ignore unexpected fields rather than erroring on them

    name = fields.String(required=True, validate=validate.Length(min=1, max=255))
    domain = fields.String(required=True, validate=validate.Length(min=1, max=255))
    industry = fields.String(required=True, validate=validate.Length(min=1, max=255))
    description = fields.String(required=False, allow_none=True, load_default=None)
    competitors = fields.List(
        fields.String(validate=validate.Length(min=1, max=255)),
        required=False,
        load_default=list,
    )
