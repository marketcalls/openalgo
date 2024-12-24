# OpenAlgo Installation Guide

## Prerequisites

Before installing OpenAlgo, ensure you have the following prerequisites installed:

- **Visual Studio Code (VS Code)** installed on Windows.
- **Python** version 3.10 or 3.11 installed.
- **Git** for cloning the repository (Download from [https://git-scm.com/downloads](https://git-scm.com/downloads)).
- **Node.js** for CSS compilation (Download from [https://nodejs.org/](https://nodejs.org/)).

## Installation Steps

1. **Install VS Code Extensions**: 
   - Open VS Code
   - Navigate to the Extensions section on the left tab
   - Install the Python, Pylance, and Jupyter extensions

2. **Clone the Repository**: 
   Open the VS Code Terminal and clone the OpenAlgo repository:
   ```bash
   git clone https://github.com/marketcalls/openalgo
   ```

3. **Install Python Dependencies**: 

   For Windows users:
   ```bash
   pip install -r requirements.txt
   ```

   For Linux/Nginx users:
   ```bash
   pip install -r requirements-nginx.txt
   ```

4. **Install Node.js Dependencies**: 
   ```bash
   cd openalgo
   npm install
   ```

5. **Configure Environment Variables**: 
   - Rename `.sample.env` to `.env` in the `openalgo` folder
   - Update the `.env` file with your specific configurations

## CSS Compilation Setup

The project uses TailwindCSS and DaisyUI for styling. The CSS needs to be compiled before running the application.

### Development Mode

For development with auto-recompilation (watches for changes):
```bash
npm run dev
```

### Production Build

For production deployment:
```bash
npm run build
```

### CSS File Structure

- Source file: `src/css/styles.css`
- Compiled output: `static/css/main.css`

When making style changes:
1. Edit the source file at `src/css/styles.css`
2. Run the appropriate npm script to compile
3. The compiled CSS will be automatically used by the templates

## Running the Application

1. **Start the Flask Application**: 

   For development:
   ```bash
   python app.py
   ```

   For production with Nginx (using eventlet):
   ```bash
   gunicorn --worker-class eventlet -w 1 app:app
   ```

   Note: When using Gunicorn, `-w 1` specifies one worker process. This is important because WebSocket connections are persistent and stateful.

2. **Access the Application**:
   - Open your browser and navigate to [http://127.0.0.1:5000](http://127.0.0.1:5000)
   - Set up your account at [http://127.0.0.1:5000/setup](http://127.0.0.1:5000/setup)
   - Log in with your credentials

## Troubleshooting

If you encounter any issues during installation:

1. **CSS not updating**:
   - Ensure Node.js is properly installed
   - Run `npm install` again
   - Check if the CSS compilation script is running
   - Clear your browser cache

2. **Python dependencies**:
   - Use a virtual environment
   - Ensure you're using Python 3.10 or 3.11
   - Try upgrading pip: `pip install --upgrade pip`

3. **WebSocket issues**:
   - Ensure you're using only one worker with Gunicorn
   - Check if your firewall allows WebSocket connections
   - Verify Socket.IO client version matches server version

For more detailed configuration instructions, visit [https://docs.openalgo.in](https://docs.openalgo.in)
