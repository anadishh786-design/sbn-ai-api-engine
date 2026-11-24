import sys

from api_client import AnswerSuccess, HealthSuccess
from config import ConfigurationError, load_config


def print_result(result):
    if isinstance(result, (HealthSuccess, AnswerSuccess)):
        if isinstance(result, HealthSuccess):
            print("Health: ok")
        else:
            print("Answer: " + result.answer)
            print("Source: " + result.source)
        print("Request ID: " + result.request_id)
        return

    print("Error [" + result.category + "]: " + result.message)
    print("Request ID: " + result.request_id)


def run():
    try:
        config = load_config()
    except ConfigurationError as error:
        print("Error [CONFIGURATION_ERROR]: " + str(error))
        return 1

    from api_client import APIClient

    with APIClient(
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
    ) as client:
        print("SBN Local AI Client")
        print("Commands: health, ask, exit")

        while True:
            try:
                command = input("> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if command == "exit":
                break
            if command == "health":
                print_result(client.health())
                continue
            if command == "ask":
                try:
                    question = input("Question: ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                print_result(client.ask(question))
                continue

            print("Use one of: health, ask, exit")

    return 0


if __name__ == "__main__":
    sys.exit(run())
