"""Smoke-test the configured Azure embedding and generation deployments."""

from scripts.azure_client import embed_text, generate
from scripts.config import get_settings


def main() -> None:
    settings = get_settings()

    embedding = embed_text("A resistor limits current in an electrical circuit.")
    print(
        f"Embedding deployment '{settings.embedding_deployment}' responded "
        + f"with {len(embedding)} dimensions."
    )

    answer = generate(
        "Reply with exactly: Azure generation deployment is responding.",
        images=None,
    )
    print(f"Generation deployment '{settings.sol_deployment}' responded: {answer}")


if __name__ == "__main__":
    main()
