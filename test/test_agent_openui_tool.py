"""The third renderer: the tool that draws it, and the prompt that teaches it.

Two things are pinned here, and both were built broken once.

**A prompt that names a tool nobody registered.** The visualization section told
the model that everything which is not a price chart goes to "the rendering
tool", and there was no such tool in any schema. Asked for a bar chart the model
did the only thing left to it and drew one out of block characters in a code
fence, which is worse than the markdown table it replaced. The registry test
below is what stops that shipping again: the tool the prompt names is asserted
to exist on the surface the prompt is injected on.

**A budget that deletes a rule to fit a reference.** ``render_sections``
enforces its cap by dropping *whole* unpinned sections from the end, with only a
log line. Adding the 8.8k OpenUI reference to a prompt already near the cap did
not truncate the reference, it silently deleted the section telling the model a
visualization is a deliberate act. The budget test asserts every surface renders
whole, so the next section to overshoot fails here rather than in production.

No agno-free path exists for the toolkit itself, so those tests skip when the
optional dependency is absent, exactly as the rest of the suite does.
"""

from __future__ import annotations

import pytest

from services.agent import prompts, viz_sink
from services.agent.builder import DEFAULT_MAX_PROMPT_CHARS
from services.agent.frames import Ui
from services.agent.tools import (
    CHAT_ONLY,
    SURFACE_CHART,
    SURFACE_CHAT,
    TOOLKITS,
    ToolContext,
    agno_available,
    select_specs,
)

requires_agno = pytest.mark.skipif(not agno_available(), reason="the agno package is not installed")


# ---------------------------------------------------------------------------
# The registry: the prompt names a tool, and the tool exists
# ---------------------------------------------------------------------------


def _spec(key: str):
    """Return the registry spec with this key.

    Args:
        key: The registry key.

    Returns:
        The matching :class:`~services.agent.tools.ToolkitSpec`.
    """
    matches = [spec for spec in TOOLKITS if spec.key == key]
    assert matches, f"no toolkit registered under {key!r}"
    return matches[0]


class TestTheRenderingTierIsRegistered:
    """The failure this file exists for: a prompt naming a tool that is absent."""

    def test_the_openui_toolkit_is_in_the_registry(self):
        spec = _spec("openui")
        assert spec.module == "services.agent.tools.openui"
        assert spec.attr == "OpenUiToolkit"

    def test_it_is_offered_on_chat_and_withheld_from_the_chart_panel(self):
        # The chart panel drives the real /trading terminal and is never taught
        # the language, so it must never be handed the tool either.
        assert _spec("openui").surfaces == CHAT_ONLY

        chat = {spec.key for spec in select_specs(ToolContext(api_key="k", surface=SURFACE_CHAT))}
        chart = {spec.key for spec in select_specs(ToolContext(api_key="k", surface=SURFACE_CHART))}
        assert "openui" in chat
        assert "openui" not in chart

    def test_it_needs_no_trading_permission(self):
        # Rendering a card mutates nothing, so a read-only session gets it.
        assert _spec("openui").requires == frozenset()
        keys = {
            spec.key
            for spec in select_specs(
                ToolContext(api_key="k", surface=SURFACE_CHAT, trading_enabled=False)
            )
        }
        assert "openui" in keys

    @requires_agno
    def test_the_built_toolkit_exposes_render_ui_by_that_name(self):
        from services.agent.tools.openui import OpenUiToolkit

        kit = OpenUiToolkit(ToolContext(api_key="k", surface=SURFACE_CHAT))
        assert [getattr(tool, "__name__", "") for tool in kit.tools] == ["render_ui"]

    @requires_agno
    def test_every_tool_the_prompt_names_is_a_tool_the_chat_surface_has(self):
        """The prompt's tool names resolve, or the model reaches for nothing."""
        from services.agent.tools import build_toolkits

        context = ToolContext(api_key="k", surface=SURFACE_CHAT, trading_enabled=False)
        available = {
            getattr(tool, "__name__", "")
            for kit in build_toolkits(context)
            for tool in getattr(kit, "tools", ())
        }
        prompt = prompts.build_system_prompt(surface=SURFACE_CHAT)
        for name in (
            "render_ui",
            "plot_price_chart",
            "plot_open_interest",
            "plot_gamma_exposure",
            "plot_volatility_surface",
        ):
            assert name in prompt, f"the prompt never mentions {name}"
            assert name in available, f"the prompt names {name} but no toolkit provides it"


# ---------------------------------------------------------------------------
# The prompt: the language is taught, on the right surface, within budget
# ---------------------------------------------------------------------------


class TestTheLanguageIsTaught:
    """A tool whose argument is a language the model was never shown is a coin flip."""

    def test_the_generated_reference_is_present_and_not_a_stub(self):
        assert prompts.OPENUI_LANG_DOC.is_file(), (
            f"{prompts.OPENUI_LANG_DOC} is missing; regenerate it with "
            "node frontend/scripts/generate-openui-prompt.mjs"
        )
        assert len(prompts.OPENUI_LANG_SECTION.body) > 4000

    def test_the_reference_carries_no_literal_undefined(self):
        # The generation call fails silently when made wrongly: every component
        # name comes out as the literal `undefined`, producing a plausible and
        # useless prompt. This is the assertion that catches that.
        assert "undefined" not in prompts.OPENUI_LANG_SECTION.body

    def test_the_scoping_preamble_comes_before_the_reference(self):
        # The generated file says "your ENTIRE response must be valid
        # openui-lang", which is true of the argument and false of the answer.
        body = prompts.OPENUI_LANG_SECTION.body
        assert body.index("does not\ndescribe your reply") < body.index("ENTIRE response")

    def test_it_is_on_chat_and_absent_from_the_chart_panel(self):
        chat = prompts.build_system_prompt(surface=SURFACE_CHAT)
        chart = prompts.build_system_prompt(surface=SURFACE_CHART)
        assert prompts.OPENUI_LANG_SECTION.title in chat
        assert prompts.OPENUI_LANG_SECTION.title not in chart

    def test_the_prompt_forbids_drawing_a_chart_out_of_characters(self):
        # The observed failure was an ASCII bar chart in a code fence, and it
        # stayed plausible to the model until the prompt ruled it out.
        prompt = prompts.build_system_prompt(surface=SURFACE_CHAT)
        assert "Never draw a chart out of characters" in prompt

    @pytest.mark.parametrize("surface", [SURFACE_CHAT, SURFACE_CHART])
    @pytest.mark.parametrize("trading", [False, True])
    @pytest.mark.parametrize("analyzer", [False, True])
    def test_every_surface_renders_whole_inside_the_budget(self, surface, trading, analyzer):
        """Overshooting the cap deletes a different section, so pin the fit."""
        kwargs = {
            "surface": surface,
            "trading_enabled": trading,
            "analyzer_mode": analyzer,
        }
        whole = prompts.build_system_prompt(**kwargs)
        capped = prompts.build_system_prompt(**kwargs, max_chars=DEFAULT_MAX_PROMPT_CHARS)
        assert whole == capped, (
            f"the {surface} prompt is {len(whole)} characters and the budget is "
            f"{DEFAULT_MAX_PROMPT_CHARS}; a whole section was dropped to fit. "
            "Raise DEFAULT_MAX_PROMPT_CHARS or shorten a section, but do not "
            "leave it dropping one silently."
        )

    def test_a_missing_reference_costs_its_own_section_and_nothing_else(self, tmp_path):
        missing = tmp_path / "not-generated.md"
        assert prompts._read_prompt_doc(missing) == ""


# ---------------------------------------------------------------------------
# The tool: what it refuses, and what reaches the browser
# ---------------------------------------------------------------------------

GOOD = 'root = Card([title])\ntitle = TextContent("Funds", "large-heavy")'


@requires_agno
class TestRenderUi:
    """The markup goes to the browser and one line goes to the model."""

    def _kit(self, sink=None):
        from services.agent.tools.openui import OpenUiToolkit

        extras = {} if sink is None else {viz_sink.SINK_KEY: sink}
        return OpenUiToolkit(ToolContext(api_key="k", surface=SURFACE_CHAT, extras=extras))

    def test_valid_markup_reaches_the_client_as_a_ui_frame(self):
        sink = viz_sink.new_sink()
        answer = self._kit(sink).render_ui(GOOD)

        frames = viz_sink.drain(sink)
        assert len(frames) == 1
        assert isinstance(frames[0], Ui)
        assert frames[0].delta == GOOD
        assert frames[0].to_dict()["type"] == "ui"
        assert "Rendered the card" in answer

    def test_the_markup_is_not_read_back_to_the_model(self):
        # The whole point of the sink: the operator reads it, the model does
        # not, so a rendered answer costs the conversation one line.
        sink = viz_sink.new_sink()
        big = 'root = Card([t])\nt = TextContent("%s", "body")' % ("x" * 4000)
        answer = self._kit(sink).render_ui(big)
        assert "x" * 100 not in answer
        assert len(answer) < 400
        assert len(viz_sink.drain(sink)[0].delta) > 4000

    def test_a_code_fence_around_the_program_is_unwrapped(self):
        sink = viz_sink.new_sink()
        self._kit(sink).render_ui(f"```openui\n{GOOD}\n```")
        assert viz_sink.drain(sink)[0].delta == GOOD

    @pytest.mark.parametrize(
        ("markup", "because"),
        [
            ("", "empty"),
            ("   ", "blank"),
            ("```\n```", "a fence holding nothing"),
            ('title = TextContent("hi", "body")', "no root binding, so it renders nothing"),
            ('root = Card([t])\nt = MarkDownRenderer("[x](https://evil.test/?q=1)")', "a URL"),
            (
                'root = Card([t])\nt = MarkDownRenderer("![x](//evil.test/?q=1)")',
                "a protocol-relative image, which a browser fetches with no click at all",
            ),
            ("root = Card([t])\n" + "t = " + '"%s"' % ("y" * 30000), "too long"),
        ],
    )
    def test_markup_it_refuses(self, markup, because):
        from agno.exceptions import RetryAgentRun

        sink = viz_sink.new_sink()
        with pytest.raises(RetryAgentRun) as caught:
            self._kit(sink).render_ui(markup)
        assert "markup" in str(caught.value), because
        assert viz_sink.drain(sink) == [], "a refused rendering must reach nobody"

    @pytest.mark.parametrize(
        "markup",
        [
            'root = Card([t])\nt = TextContent("Win rate 50//50 this week", "body")',
            'root = Card([t])\nt = TextContent("margin // collateral split", "body")',
        ],
    )
    def test_ordinary_prose_with_a_double_slash_is_not_mistaken_for_a_url(self, markup):
        # The guard must not cost the operator a card they actually asked for.
        sink = viz_sink.new_sink()
        self._kit(sink).render_ui(markup)
        assert len(viz_sink.drain(sink)) == 1

    def test_a_run_with_no_sink_says_so_rather_than_claiming_it_drew(self):
        answer = self._kit(None).render_ui(GOOD)
        assert "cannot render UI" in answer
        assert "Rendered the card" not in answer


@requires_agno
class TestBothTiersShareOneSink:
    """One sink and one hook, so a third tier is a frame type and nothing else."""

    def test_a_ui_frame_and_a_viz_frame_drain_together_in_order(self):
        sink = viz_sink.new_sink()
        viz_sink.emit_frame(sink, tool="render_ui", frame=Ui(delta=GOOD))
        viz_sink.emit(sink, tool="plot_price_chart", kind="candles", spec={"bars": []})

        frames = list(viz_sink.frame_hook(sink)("plot_price_chart", "ignored"))
        assert [frame.FRAME_TYPE for frame in frames] == ["ui", "viz"]
        assert sink == []

    def test_the_cap_bounds_ui_frames_the_same_way(self):
        sink = viz_sink.new_sink()
        for index in range(viz_sink.MAX_SINK_ENTRIES + 3):
            viz_sink.emit_frame(sink, tool="render_ui", frame=Ui(delta=f"root = Card([]) {index}"))
        assert len(sink) == viz_sink.MAX_SINK_ENTRIES
