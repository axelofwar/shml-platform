"""
SHML Agent TUI - Interactive Terminal User Interface

Built with Textual for rich terminal interfaces.
Pattern B: Full terminal app with model selection, GPU status, job tracking.

Install: pip install textual textual-dev
Run: python -m inference.router.tui
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header,
    Footer,
    Static,
    Input,
    Button,
    DataTable,
    ProgressBar,
    Label,
    Select,
    Tree,
    Log,
    Markdown,
    TabbedContent,
    TabPane,
)
from textual.binding import Binding
from textual.reactive import reactive
from textual import events
from textual.message import Message

import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any


class ModelSelector(Static):
    """Widget for selecting reasoning and execution models"""

    reasoning_model = reactive("gemini-2.0-flash-exp")
    execution_model = reactive("nemotron-coding")

    def compose(self) -> ComposeResult:
        yield Label("🧠 Reasoning Model:", classes="label")
        yield Select(
            [
                ("Gemini 2.0 Flash (Free)", "gemini-2.0-flash-exp"),
                ("Gemini 1.5 Pro", "gemini-1.5-pro"),
                ("GPT-4o Mini", "openai/gpt-4o-mini"),
                ("Claude 3.5 Sonnet", "anthropic/claude-3.5-sonnet"),
                ("Local Only", "local"),
            ],
            value="gemini-2.0-flash-exp",
            id="reasoning-select",
        )
        yield Label("⚡ Execution Model:", classes="label")
        yield Select(
            [
                ("Qwopus-27B (Local)", "nemotron-coding"),
                ("Qwen3-VL-8B (Local)", "qwen3-vl-8b"),
                ("Same as Reasoning", "same"),
            ],
            value="nemotron-coding",
            id="execution-select",
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "reasoning-select":
            self.reasoning_model = event.value
        elif event.select.id == "execution-select":
            self.execution_model = event.value


class GPUStatus(Static):
    """Widget showing GPU status"""

    def compose(self) -> ComposeResult:
        yield Static("GPU Status", classes="title")
        yield Static(id="gpu-0", classes="gpu-stat")
        yield Static(id="gpu-1", classes="gpu-stat")

    async def update_status(self):
        """Fetch and update GPU status"""
        # This would call the actual GPU status API
        gpu0 = self.query_one("#gpu-0")
        gpu1 = self.query_one("#gpu-1")

        gpu0.update("RTX 2070: [green]2.1[/green]/8GB | Qwen-VL")
        gpu1.update("RTX 3090: [yellow]16.5[/yellow]/24GB | Qwopus")


class JobTracker(Static):
    """Widget showing active jobs"""

    def compose(self) -> ComposeResult:
        yield Static("Active Jobs", classes="title")
        yield DataTable(id="jobs-table")

    def on_mount(self) -> None:
        table = self.query_one("#jobs-table", DataTable)
        table.add_columns("ID", "Type", "Status", "Time")
        # Add sample data
        table.add_row("job-001", "Training", "🔄 Running", "5m 23s")
        table.add_row("job-002", "Research", "✅ Complete", "12s")


class TaskInput(Static):
    """Widget for task input"""

    class TaskSubmitted(Message):
        def __init__(self, task: str, parallel: bool):
            self.task = task
            self.parallel = parallel
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Label("Enter your task:", classes="label")
        yield Input(
            placeholder="e.g., Check GPU status and train a YOLO model", id="task-input"
        )
        yield Horizontal(
            Button("Execute", variant="primary", id="execute-btn"),
            Button("Parallel", variant="default", id="parallel-btn"),
            Button("Cancel", variant="error", id="cancel-btn"),
            classes="button-row",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("execute-btn", "parallel-btn"):
            task_input = self.query_one("#task-input", Input)
            parallel = event.button.id == "parallel-btn"
            self.post_message(self.TaskSubmitted(task_input.value, parallel))
            task_input.value = ""


class ExecutionProgress(Static):
    """Widget showing execution progress"""

    def compose(self) -> ComposeResult:
        yield Static("Execution Progress", classes="title")
        yield Static("[Plan]", id="stage-plan", classes="stage")
        yield Static("[Execute]", id="stage-execute", classes="stage")
        yield Static("[Merge]", id="stage-merge", classes="stage")
        yield Static("[Return]", id="stage-return", classes="stage")
        yield ProgressBar(id="progress", show_eta=True)
        yield Static("", id="progress-text")

    def update_stage(self, stage: str, status: str = "active"):
        """Update a stage's status"""
        stage_widget = self.query_one(f"#stage-{stage}")
        if status == "active":
            stage_widget.update(f"[bold cyan]▶ {stage.title()}[/]")
        elif status == "complete":
            stage_widget.update(f"[green]✓ {stage.title()}[/]")
        elif status == "pending":
            stage_widget.update(f"[dim]○ {stage.title()}[/]")

    def set_progress(self, percent: float, text: str = ""):
        progress = self.query_one("#progress", ProgressBar)
        progress.update(progress=percent)

        text_widget = self.query_one("#progress-text")
        text_widget.update(text)


class OutputPanel(Static):
    """Widget showing execution output"""

    def compose(self) -> ComposeResult:
        yield TabbedContent(
            TabPane("Output", Log(id="output-log", highlight=True)),
            TabPane("Plan", Markdown(id="plan-md")),
            TabPane("Cost", Static(id="cost-summary")),
        )

    def append_output(self, text: str):
        log = self.query_one("#output-log", Log)
        log.write_line(text)

    def set_plan(self, plan_text: str):
        md = self.query_one("#plan-md", Markdown)
        md.update(plan_text)

    def set_cost(self, cost_info: Dict[str, Any]):
        cost_widget = self.query_one("#cost-summary")
        text = f"""
Cost Summary
────────────
Reasoning: ${cost_info.get('reasoning_cost', 0):.4f}
Execution: ${cost_info.get('execution_cost', 0):.4f}
Total: ${cost_info.get('total_cost', 0):.4f}

Budget Remaining: ${cost_info.get('remaining', 20.0):.2f}
"""
        cost_widget.update(text)


class BudgetIndicator(Static):
    """Widget showing budget usage"""

    budget_used = reactive(0.0)
    budget_total = reactive(20.0)

    def compose(self) -> ComposeResult:
        yield Static("Budget", classes="title")
        yield ProgressBar(id="budget-bar")
        yield Static(id="budget-text")

    def watch_budget_used(self, value: float) -> None:
        bar = self.query_one("#budget-bar", ProgressBar)
        text = self.query_one("#budget-text")

        percent = min(100, (value / self.budget_total) * 100)
        bar.update(progress=percent)

        remaining = self.budget_total - value
        color = "green" if remaining > 10 else "yellow" if remaining > 5 else "red"
        text.update(f"[{color}]${remaining:.2f}[/] / ${self.budget_total:.2f}")


class SHMLAgentTUI(App):
    """Main TUI Application"""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 3 3;
        grid-columns: 1fr 2fr 1fr;
        grid-rows: auto 1fr auto;
    }

    #header-area {
        column-span: 3;
        height: auto;
    }

    #left-panel {
        row-span: 1;
        border: solid green;
        padding: 1;
    }

    #main-panel {
        row-span: 1;
        border: solid blue;
        padding: 1;
    }

    #right-panel {
        row-span: 1;
        border: solid yellow;
        padding: 1;
    }

    #footer-area {
        column-span: 3;
        height: auto;
    }

    .title {
        text-style: bold;
        padding: 0 1;
        background: $surface;
    }

    .label {
        padding: 1 0 0 0;
    }

    .button-row {
        padding: 1 0;
    }

    .stage {
        padding: 0 1;
    }

    .gpu-stat {
        padding: 0 1;
    }

    DataTable {
        height: 10;
    }

    #budget-bar {
        width: 100%;
    }

    #output-log {
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("ctrl+c", "cancel", "Cancel"),
        Binding("f1", "help", "Help"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Container(id="header-area"):
            yield Static(
                "🤖 SHML Agent - Hybrid Cloud/Local AI Platform", classes="title"
            )

        with Container(id="left-panel"):
            yield ModelSelector()
            yield BudgetIndicator()
            yield GPUStatus()

        with Container(id="main-panel"):
            yield TaskInput()
            yield ExecutionProgress()
            yield OutputPanel()

        with Container(id="right-panel"):
            yield JobTracker()

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize when app starts"""
        # Update GPU status
        gpu_status = self.query_one(GPUStatus)
        await gpu_status.update_status()

        # Initialize progress stages
        progress = self.query_one(ExecutionProgress)
        for stage in ["plan", "execute", "merge", "return"]:
            progress.update_stage(stage, "pending")

    async def on_task_input_task_submitted(
        self, message: TaskInput.TaskSubmitted
    ) -> None:
        """Handle task submission"""
        output = self.query_one(OutputPanel)
        progress = self.query_one(ExecutionProgress)

        output.append_output(f"[bold]Task:[/] {message.task}")
        output.append_output(f"[dim]Parallel: {message.parallel}[/]")
        output.append_output("")

        # Simulate execution
        await self._execute_task(message.task, message.parallel)

    async def _execute_task(self, task: str, parallel: bool):
        """Execute a task (placeholder for real implementation)"""
        progress = self.query_one(ExecutionProgress)
        output = self.query_one(OutputPanel)
        budget = self.query_one(BudgetIndicator)

        # Stage 1: Plan
        progress.update_stage("plan", "active")
        progress.set_progress(10, "Planning with Gemini 2.0...")
        output.append_output("[cyan]► Planning task...[/]")
        await asyncio.sleep(1)

        output.set_plan(
            f"""
## Task Plan

**Original Task:** {task}

### Subtasks:
1. **Research** - Gather information (parallel)
2. **Code** - Generate implementation (parallel)
3. **Merge** - Combine results

### Estimated Cost: $0.002
"""
        )

        progress.update_stage("plan", "complete")
        output.append_output("[green]✓ Plan created[/]")

        # Stage 2: Execute
        progress.update_stage("execute", "active")
        progress.set_progress(40, "Executing subtasks...")
        output.append_output("[cyan]► Executing...[/]")

        await asyncio.sleep(2)

        progress.update_stage("execute", "complete")
        output.append_output("[green]✓ Execution complete[/]")

        # Stage 3: Merge
        progress.update_stage("merge", "active")
        progress.set_progress(80, "Merging results...")
        output.append_output("[cyan]► Merging results...[/]")

        await asyncio.sleep(1)

        progress.update_stage("merge", "complete")
        output.append_output("[green]✓ Results merged[/]")

        # Stage 4: Return
        progress.update_stage("return", "active")
        progress.set_progress(100, "Complete!")

        output.append_output("")
        output.append_output("[bold green]═══ Result ═══[/]")
        output.append_output("GPU Status: RTX 2070 (Qwen-VL) + RTX 3090 (Nemotron)")
        output.append_output("All services healthy.")

        progress.update_stage("return", "complete")

        # Update cost
        budget.budget_used += 0.002
        output.set_cost(
            {
                "reasoning_cost": 0.001,
                "execution_cost": 0.001,
                "total_cost": 0.002,
                "remaining": 20.0 - budget.budget_used,
            }
        )

    def action_refresh(self) -> None:
        """Refresh GPU status"""
        gpu_status = self.query_one(GPUStatus)
        asyncio.create_task(gpu_status.update_status())

    def action_cancel(self) -> None:
        """Cancel current execution"""
        output = self.query_one(OutputPanel)
        output.append_output("[red]Cancelled by user[/]")


def run_tui():
    """Entry point for the TUI"""
    app = SHMLAgentTUI()
    app.run()


if __name__ == "__main__":
    run_tui()
