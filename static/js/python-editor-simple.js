/*!
 * Simple Python Editor for OpenAlgo
 * A lightweight code editor with syntax highlighting and line numbers
 */

class SimplePythonEditor {
    constructor(element, options = {}) {
        this.element = element;
        this.readOnly = options.readOnly || false;
        this.value = options.value || '';
        this.onChange = options.onChange || (() => {});
        this.theme = options.theme || 'dark';
        
        this.init();
    }
    
    init() {
        // Create editor wrapper
        this.wrapper = document.createElement('div');
        this.wrapper.className = `simple-python-editor ${this.theme}`;
        
        // Create editor container with line numbers and content
        this.container = document.createElement('div');
        this.container.className = 'editor-container';
        
        // Create line numbers
        this.lineNumbersWrapper = document.createElement('div');
        this.lineNumbersWrapper.className = 'line-numbers-wrapper';
        
        // Create editor area
        this.editorWrapper = document.createElement('div');
        this.editorWrapper.className = 'editor-wrapper';
        
        // Create the actual textarea
        this.textarea = document.createElement('textarea');
        this.textarea.className = 'editor-textarea';
        this.textarea.value = this.value;
        this.textarea.readOnly = this.readOnly;
        this.textarea.spellcheck = false;
        this.textarea.wrap = 'off';
        this.textarea.autocomplete = 'off';
        this.textarea.autocorrect = 'off';
        this.textarea.autocapitalize = 'off';
        
        // Assemble the editor
        this.editorWrapper.appendChild(this.textarea);
        this.container.appendChild(this.lineNumbersWrapper);
        this.container.appendChild(this.editorWrapper);
        this.wrapper.appendChild(this.container);
        
        // Replace original element
        this.element.innerHTML = '';
        this.element.appendChild(this.wrapper);
        
        // Setup event handlers
        this.setupEventHandlers();
        
        // Initial render
        this.updateLineNumbers();
        this.adjustHeight();
    }
    
    setupEventHandlers() {
        // Handle input changes
        this.textarea.addEventListener('input', () => {
            this.value = this.textarea.value;
            this.updateLineNumbers();
            this.adjustHeight();
            this.onChange(this.value);
        });
        
        // Handle scroll sync
        this.editorWrapper.addEventListener('scroll', () => {
            this.lineNumbersWrapper.scrollTop = this.editorWrapper.scrollTop;
        });
        
        // Handle tab key
        this.textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                e.preventDefault();
                const start = this.textarea.selectionStart;
                const end = this.textarea.selectionEnd;
                const value = this.textarea.value;
                
                if (e.shiftKey) {
                    // Handle unindent
                    if (start === end) {
                        // No selection - unindent current line
                        const lineStart = value.lastIndexOf('\n', start - 1) + 1;
                        const lineEnd = value.indexOf('\n', start);
                        const endPos = lineEnd === -1 ? value.length : lineEnd;
                        const line = value.substring(lineStart, endPos);
                        
                        if (line.startsWith('    ')) {
                            this.textarea.value = value.substring(0, lineStart) + 
                                                 line.substring(4) + 
                                                 value.substring(endPos);
                            this.textarea.selectionStart = this.textarea.selectionEnd = Math.max(lineStart, start - 4);
                        } else if (line.startsWith('\t')) {
                            this.textarea.value = value.substring(0, lineStart) + 
                                                 line.substring(1) + 
                                                 value.substring(endPos);
                            this.textarea.selectionStart = this.textarea.selectionEnd = Math.max(lineStart, start - 1);
                        }
                    } else {
                        // Selection - unindent all selected lines
                        const lineStart = value.lastIndexOf('\n', start - 1) + 1;
                        const lineEnd = value.indexOf('\n', end);
                        const endPos = lineEnd === -1 ? value.length : lineEnd;
                        
                        const selectedText = value.substring(lineStart, endPos);
                        const lines = selectedText.split('\n');
                        const unindentedLines = lines.map(line => {
                            if (line.startsWith('    ')) {
                                return line.substring(4);
                            } else if (line.startsWith('\t')) {
                                return line.substring(1);
                            }
                            return line;
                        });
                        
                        const unindented = unindentedLines.join('\n');
                        this.textarea.value = value.substring(0, lineStart) + unindented + value.substring(endPos);
                        
                        // Adjust selection
                        const startLineUnindent = lines[0].length - unindentedLines[0].length;
                        const totalUnindent = selectedText.length - unindented.length;
                        this.textarea.selectionStart = start - startLineUnindent;
                        this.textarea.selectionEnd = end - totalUnindent;
                    }
                } else {
                    // Handle indent
                    if (start === end) {
                        // No selection - insert 4 spaces
                        this.textarea.value = value.substring(0, start) + '    ' + value.substring(end);
                        this.textarea.selectionStart = this.textarea.selectionEnd = start + 4;
                    } else {
                        // Selection - indent all selected lines
                        const lineStart = value.lastIndexOf('\n', start - 1) + 1;
                        const lineEnd = value.indexOf('\n', end);
                        const endPos = lineEnd === -1 ? value.length : lineEnd;
                        
                        const selectedText = value.substring(lineStart, endPos);
                        const lines = selectedText.split('\n');
                        const indented = lines.map(line => '    ' + line).join('\n');
                        
                        this.textarea.value = value.substring(0, lineStart) + indented + value.substring(endPos);
                        
                        // Adjust selection
                        this.textarea.selectionStart = start + 4;
                        this.textarea.selectionEnd = end + (lines.length * 4);
                    }
                }
                
                this.value = this.textarea.value;
                this.updateLineNumbers();
                this.adjustHeight();
                this.onChange(this.value);
            }
        });
        
        // Handle line breaks
        this.textarea.addEventListener('keyup', () => {
            this.updateLineNumbers();
            this.adjustHeight();
        });
        
        // Handle paste
        this.textarea.addEventListener('paste', () => {
            setTimeout(() => {
                this.updateLineNumbers();
                this.adjustHeight();
            }, 0);
        });
    }
    
    updateLineNumbers() {
        const lines = (this.value || '').split('\n');
        const lineCount = lines.length;
        
        // Generate line numbers
        let lineNumbersHtml = '';
        for (let i = 1; i <= lineCount; i++) {
            lineNumbersHtml += `<div class="line-number">${i}</div>`;
        }
        
        this.lineNumbersWrapper.innerHTML = lineNumbersHtml;
    }
    
    adjustHeight() {
        // Auto-adjust textarea height to fit content
        this.textarea.style.height = 'auto';
        const scrollHeight = this.textarea.scrollHeight;
        
        // Set minimum height
        const minHeight = 600;
        const actualHeight = Math.max(scrollHeight, minHeight);
        
        this.textarea.style.height = actualHeight + 'px';
        
        // Also adjust line numbers container height
        if (this.lineNumbersWrapper) {
            this.lineNumbersWrapper.style.height = actualHeight + 'px';
        }
    }
    
    getValue() {
        return this.value;
    }
    
    setValue(value) {
        this.value = value;
        this.textarea.value = value;
        this.updateLineNumbers();
        this.adjustHeight();
        // Force a reflow to ensure proper rendering
        this.textarea.style.display = 'none';
        this.textarea.offsetHeight; // Trigger reflow
        this.textarea.style.display = '';
    }
    
    setReadOnly(readOnly) {
        this.readOnly = readOnly;
        this.textarea.readOnly = readOnly;
        this.wrapper.classList.toggle('read-only', readOnly);
    }
    
    setTheme(theme) {
        this.wrapper.classList.remove(this.theme);
        this.theme = theme;
        this.wrapper.classList.add(this.theme);
    }
    
    focus() {
        this.textarea.focus();
    }
    
    getSelection() {
        return {
            start: this.textarea.selectionStart,
            end: this.textarea.selectionEnd,
            text: this.textarea.value.substring(this.textarea.selectionStart, this.textarea.selectionEnd)
        };
    }
    
    setSelection(start, end) {
        this.textarea.selectionStart = start;
        this.textarea.selectionEnd = end || start;
        this.textarea.focus();
    }
}

// Export for use
window.SimplePythonEditor = SimplePythonEditor;