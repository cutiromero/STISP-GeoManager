"""Expose Hermes web-run presentation callbacks on its SSE stream."""

import asyncio
from contextvars import ContextVar
from functools import wraps

presentation = ContextVar("web_run_presentation", default=None)


def enable_web_events():
    from gateway import session_api_turn
    from gateway.platforms import api_server, api_server_runs

    execute = api_server_runs._execute_run
    observe = session_api_turn.observe_api_turn
    create_agent = api_server.APIServerAdapter._create_agent

    @wraps(execute)
    async def execute_run(adapter, run, *, _api_server):
        loop = asyncio.get_running_loop()

        def publish(kind, **fields):
            event = api_server_runs._run_event(run.run_id, kind, **fields)
            loop.call_soon_threadsafe(run.put_event, event)

        token = presentation.set(
            (
                run,
                lambda text: publish("reasoning.delta", delta=text),
                lambda text, *, already_streamed=False: publish(
                    "message.interim", text=text, already_streamed=already_streamed
                ),
            )
        )
        try:
            return await execute(adapter, run, _api_server=_api_server)
        finally:
            presentation.reset(token)

    @wraps(observe)
    async def observe_run(admission, **kwargs):
        current = presentation.get()
        if current and current[0].admission is admission:
            kwargs.setdefault("reasoning_callback", current[1])
            kwargs.setdefault("interim_assistant_callback", current[2])
        return await observe(admission, **kwargs)

    @wraps(create_agent)
    def create_streaming_agent(adapter, *args, **kwargs):
        current = presentation.get()
        if current and current[0].admission is None:
            kwargs.setdefault("reasoning_callback", current[1])
        return create_agent(adapter, *args, **kwargs)

    api_server_runs._execute_run = execute_run
    session_api_turn.observe_api_turn = observe_run
    api_server.APIServerAdapter._create_agent = create_streaming_agent


if __name__ == "__main__":
    import sys

    from hermes_cli.main import main

    enable_web_events()
    sys.exit(main())
