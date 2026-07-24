"""
Command-line interface for emotion analysis.

Provides commands for:
- Analyzing single messages
- Batch processing from files
- Running demos with preset messages
- JSON output for machine-readable results
"""
import click
import json
from pathlib import Path
from typing import List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from .pipeline import EmotionPipeline
from .models import EmotionAnalysis
from .config import EmotionConfig


# Initialize console for rich output
console = Console()

# Global pipeline instance (lazy-loaded)
_pipeline = None


def get_pipeline(config_path: str = None) -> EmotionPipeline:
    """Get or create the emotion pipeline instance"""
    global _pipeline
    if _pipeline is None:
        if config_path:
            # Load custom config if provided
            config = EmotionConfig()  # TODO: Load from file if needed
        else:
            config = EmotionConfig()
        _pipeline = EmotionPipeline(config)
    return _pipeline


def format_analysis_table(analysis: EmotionAnalysis) -> Table:
    """Format analysis results as a rich table"""
    table = Table(title="Emotion Analysis Results", box=box.ROUNDED)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")
    
    # Add rows
    table.add_row("Message", analysis.message)
    table.add_row("Sentiment", analysis.sentiment.value)
    table.add_row("Emotion", f"{analysis.emotion.value} ({analysis.emotion_confidence:.2%})")
    table.add_row("Purchase Intent", f"{analysis.purchase_intent_score}/10")
    table.add_row("VADER Compound", f"{analysis.vader_compound:.3f}")
    table.add_row("Positive", f"{analysis.vader_pos:.3f}")
    table.add_row("Negative", f"{analysis.vader_neg:.3f}")
    table.add_row("Neutral", f"{analysis.vader_neu:.3f}")
    table.add_row("Contains Question", "Yes" if analysis.contains_question else "No")
    table.add_row("Processing Time", f"{analysis.processing_time_ms:.2f}ms")
    
    return table


def format_batch_table(results: List[EmotionAnalysis]) -> Table:
    """Format batch results as a rich table"""
    table = Table(title=f"Batch Analysis Results ({len(results)} messages)", box=box.ROUNDED)
    table.add_column("#", style="dim", width=4)
    table.add_column("Message", style="white", max_width=40)
    table.add_column("Sentiment", style="cyan")
    table.add_column("Emotion", style="magenta")
    table.add_column("Intent", style="green", justify="right")
    
    for idx, analysis in enumerate(results, 1):
        # Truncate long messages
        message_preview = analysis.message[:37] + "..." if len(analysis.message) > 40 else analysis.message
        table.add_row(
            str(idx),
            message_preview,
            analysis.sentiment.value,
            analysis.emotion.value,
            f"{analysis.purchase_intent_score}/10"
        )
    
    return table


@click.group()
def cli():
    """Emotion Analysis CLI - Analyze sentiment, emotion, and purchase intent"""
    pass


@cli.command()
@click.argument('text')
@click.option('--json', 'output_json', is_flag=True, help='Output results as JSON')
@click.option('--config', 'config_path', type=click.Path(exists=True), help='Path to custom config file')
def analyze(text: str, output_json: bool, config_path: str):
    """Analyze a single message for emotion and sentiment
    
    Examples:
        emotion-cli analyze "I love this product!"
        emotion-cli analyze "How much does it cost?" --json
    """
    try:
        # Get pipeline
        pipeline = get_pipeline(config_path)
        
        # Analyze message
        result = pipeline.analyze(text)
        
        if output_json:
            # Output as JSON
            output = result.model_dump(mode='json')
            # Convert datetime to ISO string
            output['timestamp'] = output['timestamp'].isoformat() if hasattr(output['timestamp'], 'isoformat') else str(output['timestamp'])
            click.echo(json.dumps(output, indent=2))
        else:
            # Rich formatted output
            table = format_analysis_table(result)
            console.print(table)
    
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise click.Abort()


@cli.command()
@click.argument('file', type=click.Path(exists=True))
@click.option('--json', 'output_json', is_flag=True, help='Output results as JSON')
@click.option('--config', 'config_path', type=click.Path(exists=True), help='Path to custom config file')
def batch(file: str, output_json: bool, config_path: str):
    """Process messages from a file (one message per line)
    
    Examples:
        emotion-cli batch messages.txt
        emotion-cli batch messages.txt --json > results.json
    """
    try:
        # Read messages from file
        file_path = Path(file)
        
        if not file_path.exists():
            console.print(f"[red]Error:[/red] File not found: {file}")
            raise click.Abort()
        
        with open(file_path, 'r', encoding='utf-8') as f:
            messages = [line.strip() for line in f if line.strip()]
        
        if not messages:
            console.print("[yellow]Warning:[/yellow] No messages found in file")
            return
        
        # Get pipeline
        pipeline = get_pipeline(config_path)
        
        # Process messages
        if not output_json:
            console.print(f"Processing {len(messages)} messages...")
        
        results = []
        for message in messages:
            result = pipeline.analyze(message)
            results.append(result)
        
        if output_json:
            # Output as JSON array
            output = []
            for result in results:
                item = result.model_dump(mode='json')
                item['timestamp'] = item['timestamp'].isoformat() if hasattr(item['timestamp'], 'isoformat') else str(item['timestamp'])
                output.append(item)
            click.echo(json.dumps(output, indent=2))
        else:
            # Rich formatted table
            table = format_batch_table(results)
            console.print(table)
            
            # Summary statistics
            avg_intent = sum(r.purchase_intent_score for r in results) / len(results)
            console.print(f"\n[cyan]Average Purchase Intent:[/cyan] {avg_intent:.1f}/10")
    
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise click.Abort()


@cli.command()
@click.option('--json', 'output_json', is_flag=True, help='Output results as JSON')
def demo(output_json: bool):
    """Run a demonstration with preset example messages
    
    Shows the emotion analysis system processing various types of messages
    including positive, negative, questions, and purchase intent.
    """
    # Preset demo messages
    demo_messages = [
        "I absolutely love this! It's amazing and I want it now! 😍",
        "This is terrible and disappointing. I hate it.",
        "I'm not sure about this product. Can you tell me more?",
        "How much does this cost? I'm interested in buying.",
        "Meh, it's okay I guess. Nothing special.",
        "OMG YES! Take my money! Where can I purchase?? 💰",
        "I'm so sad and frustrated with this experience 😢",
        "Wow! This surprised me. Better than I expected!",
    ]
    
    try:
        # Get pipeline
        pipeline = get_pipeline()
        
        if not output_json:
            console.print(Panel.fit(
                "[bold cyan]Emotion Analysis Demo[/bold cyan]\n"
                f"Processing {len(demo_messages)} example messages...",
                border_style="cyan"
            ))
            console.print()
        
        # Process all messages
        results = []
        for message in demo_messages:
            result = pipeline.analyze(message)
            results.append(result)
            
            if not output_json:
                # Show each result
                table = format_analysis_table(result)
                console.print(table)
                console.print()
        
        if output_json:
            # Output as JSON array
            output = []
            for result in results:
                item = result.model_dump(mode='json')
                item['timestamp'] = item['timestamp'].isoformat() if hasattr(item['timestamp'], 'isoformat') else str(item['timestamp'])
                output.append(item)
            click.echo(json.dumps(output, indent=2))
        else:
            # Summary
            console.print(Panel.fit(
                f"[bold green]Demo Complete![/bold green]\n"
                f"Processed {len(results)} messages successfully",
                border_style="green"
            ))
    
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise click.Abort()


if __name__ == '__main__':
    cli()
