"""Allow `python -m w9_onboarding ...` as an alternate to the `w9-onboard` CLI."""

from w9_onboarding.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
