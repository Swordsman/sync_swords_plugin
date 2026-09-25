#!/usr/bin/env python3
"""
Extension system for AI Hypervisor.

Clean plugin architecture for optional capabilities:
- Input prediction/interception
- Protocol extensions  
- Custom screen analyzers
- Event processors
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


class Extension(ABC):
    """Base class for hypervisor extensions."""
    
    name: str = "unnamed"
    version: str = "0.1.0"
    
    @abstractmethod
    def initialize(self, hypervisor) -> bool:
        """
        Initialize extension with hypervisor reference.
        
        Returns True if initialized successfully.
        """
        pass
    
    def shutdown(self):
        """Cleanup extension resources."""
        pass


class InputInterceptor(Extension):
    """
    Extension point for intercepting/modifying user input.
    
    Called before input is sent to PTY.
    Can be used for:
    - Password detection/masking
    - Input prediction
    - Command validation
    - Keystroke logging
    """
    
    @abstractmethod
    def on_input(self, data: bytes) -> Optional[bytes]:
        """
        Process raw input bytes.
        
        Returns:
            Modified bytes to send instead, or
            None to pass through unchanged, or
            b'' to drop the input
        """
        pass


class ScreenAnalyzer(Extension):
    """
    Extension point for analyzing screen state.
    
    Called periodically with current screen buffer.
    Can be used for:
    - Pattern detection
    - Usage tracking
    - Anomaly detection
    """
    
    @abstractmethod
    def on_screen_update(self, screen_text: str, scrollback: List[str]):
        """
        Called when screen updates.
        
        Args:
            screen_text: Current screen content
            scrollback: Committed scrollback lines
        """
        pass


class ProtocolExtension(Extension):
    """
    Extension point for protocol handling.
    
    Can add support for new protocols or extend existing ones.
    """
    
    @abstractmethod
    def get_supported_protocols(self) -> List[str]:
        """Return list of protocol names this extension handles."""
        pass
    
    @abstractmethod
    def on_message(self, protocol: str, direction: str, message: Any) -> Optional[Any]:
        """
        Process protocol message.
        
        Returns modified message or None to pass through.
        """
        pass


class ExtensionManager:
    """Manages hypervisor extensions."""
    
    def __init__(self):
        self.extensions: List[Extension] = []
        self.input_interceptors: List[InputInterceptor] = []
        self.screen_analyzers: List[ScreenAnalyzer] = []
        self.protocol_extensions: List[ProtocolExtension] = []
    
    def register(self, ext: Extension) -> bool:
        """Register an extension."""
        self.extensions.append(ext)
        
        # Sort into appropriate lists
        if isinstance(ext, InputInterceptor):
            self.input_interceptors.append(ext)
        if isinstance(ext, ScreenAnalyzer):
            self.screen_analyzers.append(ext)
        if isinstance(ext, ProtocolExtension):
            self.protocol_extensions.append(ext)
        
        return True
    
    def initialize_all(self, hypervisor) -> Dict[str, bool]:
        """Initialize all extensions."""
        results = {}
        for ext in self.extensions:
            try:
                results[ext.name] = ext.initialize(hypervisor)
            except Exception as e:
                results[ext.name] = False
        return results
    
    def shutdown_all(self):
        """Shutdown all extensions."""
        for ext in self.extensions:
            try:
                ext.shutdown()
            except:
                pass
    
    def process_input(self, data: bytes) -> bytes:
        """Run input through all interceptors."""
        for interceptor in self.input_interceptors:
            try:
                result = interceptor.on_input(data)
                if result is not None:
                    data = result
                if data == b'':
                    break  # Input was dropped
            except Exception:
                pass
        return data
    
    def analyze_screen(self, screen_text: str, scrollback: List[str]):
        """Notify all screen analyzers."""
        for analyzer in self.screen_analyzers:
            try:
                analyzer.on_screen_update(screen_text, scrollback)
            except:
                pass


# Built-in extensions

class InputPredictorExtension(InputInterceptor):
    """
    Built-in input prediction extension.
    
    Optional - only loaded if anticipatory input handling is needed.
    """
    
    name = "input-predictor"
    version = "0.1.0"
    
    def __init__(self):
        self.predictor = None
        self.enabled = True
    
    def initialize(self, hypervisor) -> bool:
        from input_predictor import InputPredictor
        self.predictor = InputPredictor()
        # Wire up callbacks if needed
        return True
    
    def on_input(self, data: bytes) -> Optional[bytes]:
        if not self.enabled or not self.predictor:
            return None
        
        # Process for prediction (doesn't modify input)
        self.predictor.process_input(data)
        
        # Return None to pass through unchanged
        return None
    
    def enable(self):
        self.enabled = True
    
    def disable(self):
        self.enabled = False


class SensitiveDataFilter(InputInterceptor):
    """
    Detect and optionally mask sensitive input.
    
    Optional security extension.
    """
    
    name = "sensitive-filter"
    version = "0.1.0"
    
    def __init__(self):
        import re
        self.patterns = [
            (re.compile(r'(password|secret|key|token)[:\s]*', re.I), 'credential'),
        ]
        self.mask_mode = 'detect'  # 'detect', 'mask', 'block'
    
    def initialize(self, hypervisor) -> bool:
        return True
    
    def on_input(self, data: bytes) -> Optional[bytes]:
        try:
            text = data.decode('utf-8', errors='replace')
        except:
            return None
        
        for pattern, label in self.patterns:
            if pattern.search(text):
                if self.mask_mode == 'detect':
                    # Just log, don't modify
                    pass
                elif self.mask_mode == 'mask':
                    # Replace with asterisks
                    return b'*' * len(data)
                elif self.mask_mode == 'block':
                    # Drop the input
                    return b''
        
        return None


# Usage example in hypervisor:
# 
# from extensions import ExtensionManager, InputPredictorExtension
# 
# self.extensions = ExtensionManager()
# if config.enable_input_prediction:
#     self.extensions.register(InputPredictorExtension())
# self.extensions.initialize_all(self)
