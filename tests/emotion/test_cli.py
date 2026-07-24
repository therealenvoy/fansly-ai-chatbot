"""
Tests for the Emotion Analysis CLI tool.

Tests cover:
- Single message analysis via CLI
- Batch file processing
- JSON output formatting
- Demo command
"""
import pytest
import json
import tempfile
from pathlib import Path
from click.testing import CliRunner

from src.emotion.cli import cli


@pytest.fixture
def runner():
    """Create Click CLI test runner"""
    return CliRunner()


@pytest.fixture
def sample_messages_file():
    """Create temporary file with sample messages"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("I love this! How much does it cost?\n")
        f.write("This is terrible and disappointing.\n")
        f.write("I'm not sure about this.\n")
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


class TestCliAnalyzeMessage:
    """Tests for the 'analyze' command (single message)"""
    
    def test_cli_analyze_message(self, runner):
        """Test analyzing a single message via CLI"""
        # Arrange
        message = "I love this! How much does it cost?"
        
        # Act
        result = runner.invoke(cli, ['analyze', message])
        
        # Assert
        assert result.exit_code == 0
        assert message in result.output
        assert "Sentiment" in result.output
        assert "Emotion" in result.output
        assert "Purchase Intent" in result.output
    
    def test_cli_analyze_with_json_output(self, runner):
        """Test analyzing a message with JSON output format"""
        # Arrange
        message = "I love this product!"
        
        # Act
        result = runner.invoke(cli, ['analyze', message, '--json'])
        
        # Assert
        assert result.exit_code == 0
        
        # Parse JSON output
        data = json.loads(result.output)
        assert data['message'] == message
        assert 'sentiment' in data
        assert 'emotion' in data
        assert 'purchase_intent_score' in data
        assert 'vader_compound' in data


class TestCliBatchFile:
    """Tests for the 'batch' command (file processing)"""
    
    def test_cli_batch_file(self, runner, sample_messages_file):
        """Test processing messages from a file"""
        # Act
        result = runner.invoke(cli, ['batch', sample_messages_file])
        
        # Assert
        assert result.exit_code == 0
        assert "Processing" in result.output or "Processed" in result.output
        # Verify all messages were processed
        assert "I love this!" in result.output or "3" in result.output  # 3 messages
    
    def test_cli_batch_with_json_output(self, runner, sample_messages_file):
        """Test batch processing with JSON output"""
        # Act
        result = runner.invoke(cli, ['batch', sample_messages_file, '--json'])
        
        # Assert
        assert result.exit_code == 0
        
        # Parse JSON output
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 3
        
        # Verify structure of first result
        assert 'message' in data[0]
        assert 'sentiment' in data[0]
        assert 'emotion' in data[0]
    
    def test_cli_batch_nonexistent_file(self, runner):
        """Test batch processing with non-existent file"""
        # Act
        result = runner.invoke(cli, ['batch', '/nonexistent/file.txt'])
        
        # Assert
        assert result.exit_code != 0
        assert "Error" in result.output or "not found" in result.output.lower()


class TestCliJsonOutput:
    """Tests for JSON output formatting"""
    
    def test_cli_json_output(self, runner):
        """Test that JSON output is properly formatted and parseable"""
        # Arrange
        message = "This is a test message with mixed emotions! But also sad..."
        
        # Act
        result = runner.invoke(cli, ['analyze', message, '--json'])
        
        # Assert
        assert result.exit_code == 0
        
        # Verify valid JSON
        data = json.loads(result.output)
        
        # Verify required fields
        required_fields = [
            'message', 'sentiment', 'emotion', 'emotion_confidence',
            'purchase_intent_score', 'vader_compound', 'vader_pos',
            'vader_neg', 'vader_neu', 'contains_question'
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Verify data types and ranges
        assert isinstance(data['vader_compound'], float)
        assert -1.0 <= data['vader_compound'] <= 1.0
        assert isinstance(data['emotion_confidence'], float)
        assert 0.0 <= data['emotion_confidence'] <= 1.0
        assert isinstance(data['purchase_intent_score'], int)
        assert 0 <= data['purchase_intent_score'] <= 10


class TestCliDemo:
    """Tests for the 'demo' command"""
    
    def test_cli_demo_command(self, runner):
        """Test the demo command runs successfully"""
        # Act
        result = runner.invoke(cli, ['demo'])
        
        # Assert
        assert result.exit_code == 0
        assert "Demo" in result.output or "Example" in result.output or "Message" in result.output
        # Should show multiple example messages (count "Sentiment" in table rows, not "Sentiment:")
        assert result.output.count("Sentiment") >= 3 or result.output.count('"sentiment"') >= 3
