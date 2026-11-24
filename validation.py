import re


MIN_QUESTION_LENGTH = 1
MAX_QUESTION_LENGTH = 500


class ValidationError(ValueError):
    pass


def validate_question(question):
    if not isinstance(question, str):
        raise ValidationError("Question must be a string.")

    trimmed = question.strip()
    if len(trimmed) < MIN_QUESTION_LENGTH:
        raise ValidationError("Question must not be blank.")
    if len(trimmed) > MAX_QUESTION_LENGTH:
        raise ValidationError("Question must be 500 characters or fewer.")

    return trimmed
