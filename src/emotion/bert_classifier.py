"""
BERT-based emotion classification for accurate emotion detection
"""
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from typing import Dict
from .config import EmotionConfig


class BERTEmotionClassifier:
    """Transformer-based emotion classification using DistilRoBERTa"""
    
    def __init__(self, config: EmotionConfig = None):
        self.config = config or EmotionConfig()
        device_str = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device_str
        self._torch_device = torch.device(device_str)
        
        # Load model and tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(self.config.bert_model)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            self.config.bert_model
        ).to(self._torch_device)
        
        # Emotion labels (model-specific)
        self.id2label = self.model.config.id2label
    
    def classify(self, text: str) -> Dict[str, any]:
        """
        Classify emotion in text
        
        Args:
            text: Input message
            
        Returns:
            Dict with emotion and confidence
        """
        # Tokenize
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True
        ).to(self._torch_device)
        
        # Get predictions
        with torch.no_grad():
            outputs = self.model(**inputs)
            probs = torch.softmax(outputs.logits, dim=-1)
            
        # Get top prediction
        confidence, predicted_id = torch.max(probs, dim=-1)
        emotion = self.id2label[predicted_id.item()]
        
        return {
            "emotion": emotion,
            "confidence": confidence.item(),
            "all_scores": {
                self.id2label[i]: probs[0][i].item() 
                for i in range(len(self.id2label))
            }
        }
    
    def batch_classify(self, texts: list) -> list:
        """
        Classify emotions for multiple texts
        
        Args:
            texts: List of messages
            
        Returns:
            List of emotion results
        """
        results = []
        for text in texts:
            results.append(self.classify(text))
        return results
