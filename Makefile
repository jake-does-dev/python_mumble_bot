# Run the test suites for every component locally.
#
# The source isn't bind-mounted into the running containers, so we run each
# suite by mounting the repo into the matching service image (which already has
# that component's runtime deps) and installing pytest ephemerally. Nothing
# running is touched, and no host Python/deps are required.
#
#   make test            # run all four suites
#   make test-core       # pmb_core (shared MIDI parsing)
#   make test-web        # web service layer (commands / presence / stats)
#   make test-discord    # discord bot (playback / mixer)
#   make test-mumble     # mumble bot
#
# Image names default to the local compose-built images; override if yours
# differ, e.g.  make test WEB_IMG=myrepo-web
BOT_IMG     ?= deploy-pmb_bot
WEB_IMG     ?= deploy-pmb_web
DISCORD_IMG ?= pmb-discord-disc_bot

REPO := $(shell pwd)
RUN  := docker run --rm -v "$(REPO)":/src --entrypoint sh

.PHONY: test test-core test-web test-discord test-mumble

test: test-core test-web test-discord test-mumble
	@echo "\n✅ All suites passed."

test-core:
	@echo "######## pmb_core ########"
	$(RUN) -w /src $(BOT_IMG) -c 'pip install -q pytest 2>/dev/null; python -m pytest pmb_core/test "$$@"' -- $(ARGS)

test-web:
	@echo "######## web ########"
	$(RUN) -w /src/web $(WEB_IMG) -c 'pip install -q pytest mongomock 2>/dev/null; PYTHONPATH=/src/web python -m pytest test "$$@"' -- $(ARGS)

test-discord:
	@echo "######## discord ########"
	$(RUN) -w /src/discord_bot $(DISCORD_IMG) -c 'pip install -q pytest 2>/dev/null; python -m pytest test "$$@"' -- $(ARGS)

test-mumble:
	@echo "######## mumble ########"
	$(RUN) -w /src/mumble_bot $(BOT_IMG) -c 'pip install -q pytest 2>/dev/null; python -m pytest test "$$@"' -- $(ARGS)
