/*!
 * CodeMirror Python Editor Bundle for OpenAlgo
 * Includes: basic-setup, python language support, dark theme
 * Built without external CDN dependencies
 */

// Simple CodeMirror-like editor implementation for Python
class PythonEditor {
    constructor(element, options = {}) {
        this.element = element;
        this.readOnly = options.readOnly || false;
        this.value = options.value || '';
        this.onChange = options.onChange || (() => {});
        this.theme = options.theme || 'dark';
        
        this.init();
    }
    
    init() {
        // Create editor structure
        this.container = document.createElement('div');
        this.container.className = `python-editor ${this.theme}`;
        
        // Create line numbers container
        this.lineNumbers = document.createElement('div');
        this.lineNumbers.className = 'line-numbers';
        
        // Create textarea
        this.textarea = document.createElement('textarea');
        this.textarea.className = 'editor-textarea';
        this.textarea.value = this.value;
        this.textarea.readOnly = this.readOnly;
        this.textarea.spellcheck = false;
        this.textarea.autocapitalize = 'off';
        this.textarea.autocomplete = 'off';
        
        // Create highlighted code overlay
        this.codeDisplay = document.createElement('pre');
        this.codeDisplay.className = 'code-display';
        
        this.codeContent = document.createElement('code');
        this.codeContent.className = 'language-python';
        this.codeDisplay.appendChild(this.codeContent);
        
        // Assemble editor
        const editorContent = document.createElement('div');
        editorContent.className = 'editor-content';
        editorContent.appendChild(this.codeDisplay);
        editorContent.appendChild(this.textarea);
        
        this.container.appendChild(this.lineNumbers);
        this.container.appendChild(editorContent);
        
        // Replace original element
        this.element.innerHTML = '';
        this.element.appendChild(this.container);
        
        // Set up event handlers
        this.setupEventHandlers();
        
        // Initial render
        this.updateDisplay();
    }
    
    setupEventHandlers() {
        // Handle input
        this.textarea.addEventListener('input', () => {
            this.value = this.textarea.value;
            this.updateDisplay();
            this.onChange(this.value);
        });
        
        // Handle scroll sync
        this.textarea.addEventListener('scroll', () => {
            this.codeDisplay.scrollTop = this.textarea.scrollTop;
            this.codeDisplay.scrollLeft = this.textarea.scrollLeft;
            this.lineNumbers.scrollTop = this.textarea.scrollTop;
        });
        
        // Handle tab key
        this.textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                e.preventDefault();
                const start = this.textarea.selectionStart;
                const end = this.textarea.selectionEnd;
                const value = this.textarea.value;
                
                if (e.shiftKey) {
                    // Unindent
                    const beforeStart = value.lastIndexOf('\n', start - 1) + 1;
                    const afterEnd = value.indexOf('\n', end);
                    const endPos = afterEnd === -1 ? value.length : afterEnd;
                    
                    const lines = value.substring(beforeStart, endPos).split('\n');
                    const unindented = lines.map(line => line.replace(/^(    |\t)/, '')).join('\n');
                    
                    this.textarea.value = value.substring(0, beforeStart) + unindented + value.substring(endPos);
                    this.textarea.selectionStart = start - (lines[0].length - lines[0].replace(/^(    |\t)/, '').length);
                    this.textarea.selectionEnd = end - (value.substring(beforeStart, endPos).length - unindented.length);
                } else if (start === end) {
                    // Insert tab
                    this.textarea.value = value.substring(0, start) + '    ' + value.substring(end);
                    this.textarea.selectionStart = this.textarea.selectionEnd = start + 4;
                } else {
                    // Indent selection
                    const beforeStart = value.lastIndexOf('\n', start - 1) + 1;
                    const afterEnd = value.indexOf('\n', end);
                    const endPos = afterEnd === -1 ? value.length : afterEnd;
                    
                    const lines = value.substring(beforeStart, endPos).split('\n');
                    const indented = lines.map(line => '    ' + line).join('\n');
                    
                    this.textarea.value = value.substring(0, beforeStart) + indented + value.substring(endPos);
                    this.textarea.selectionStart = start + 4;
                    this.textarea.selectionEnd = end + (indented.length - value.substring(beforeStart, endPos).length);
                }
                
                this.value = this.textarea.value;
                this.updateDisplay();
                this.onChange(this.value);
            }
        });
    }
    
    updateDisplay() {
        // Update line numbers
        const lines = this.value.split('\n');
        const lineNumbersHtml = lines.map((_, i) => `<div>${i + 1}</div>`).join('');
        this.lineNumbers.innerHTML = lineNumbersHtml;
        
        // Update highlighted code
        this.codeContent.textContent = this.value;
        this.highlightSyntax();
        
        // Adjust textarea height
        this.textarea.style.height = 'auto';
        this.textarea.style.height = this.textarea.scrollHeight + 'px';
    }
    
    highlightSyntax() {
        let html = this.escapeHtml(this.value);
        
        // Python keywords
        const keywords = [
            'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
            'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
            'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is',
            'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return',
            'try', 'while', 'with', 'yield'
        ];
        
        const builtins = [
            'abs', 'all', 'any', 'ascii', 'bin', 'bool', 'bytes', 'callable',
            'chr', 'classmethod', 'compile', 'complex', 'delattr', 'dict', 'dir',
            'divmod', 'enumerate', 'eval', 'exec', 'filter', 'float', 'format',
            'frozenset', 'getattr', 'globals', 'hasattr', 'hash', 'help', 'hex',
            'id', 'input', 'int', 'isinstance', 'issubclass', 'iter', 'len',
            'list', 'locals', 'map', 'max', 'memoryview', 'min', 'next', 'object',
            'oct', 'open', 'ord', 'pow', 'print', 'property', 'range', 'repr',
            'reversed', 'round', 'set', 'setattr', 'slice', 'sorted', 'staticmethod',
            'str', 'sum', 'super', 'tuple', 'type', 'vars', 'zip'
        ];
        
        // Highlight strings (both single and double quotes, including triple quotes)
        html = html.replace(/("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g, 
            '<span class="string">$1</span>');
        
        // Highlight comments
        html = html.replace(/(#[^\n]*)/g, '<span class="comment">$1</span>');
        
        // Highlight numbers
        html = html.replace(/\b(\d+\.?\d*)\b/g, '<span class="number">$1</span>');
        
        // Highlight keywords
        keywords.forEach(keyword => {
            const regex = new RegExp(`\\b(${keyword})\\b`, 'g');
            html = html.replace(regex, '<span class="keyword">$1</span>');
        });
        
        // Highlight built-in functions
        builtins.forEach(builtin => {
            const regex = new RegExp(`\\b(${builtin})\\b`, 'g');
            html = html.replace(regex, '<span class="builtin">$1</span>');
        });
        
        // Highlight function definitions
        html = html.replace(/\b(def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)/g, 
            '<span class="keyword">$1</span> <span class="function">$2</span>');
        
        // Highlight decorators
        html = html.replace(/(@[a-zA-Z_][a-zA-Z0-9_]*)/g, '<span class="decorator">$1</span>');
        
        this.codeContent.innerHTML = html;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    getValue() {
        return this.value;
    }
    
    setValue(value) {
        this.value = value;
        this.textarea.value = value;
        this.updateDisplay();
    }
    
    setReadOnly(readOnly) {
        this.readOnly = readOnly;
        this.textarea.readOnly = readOnly;
        this.container.classList.toggle('read-only', readOnly);
    }
    
    focus() {
        this.textarea.focus();
    }
}

// Export for use
window.PythonEditor = PythonEditor;