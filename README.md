# SRT Comparison Tool - Desktop Application

A desktop application for **comparing and managing subtitle (SRT) files** with bilingual support. Features automatic English detection, edit capabilities, and export functionality.

## Features

- 📊 **Compare SRT files** with detailed analysis
- 🌐 **Bilingual subtitle support** - automatic English detection (first or second position)
- ✏️ **Edit and save** comparison results
- 💾 **Download merged bilingual SRT** files with sorted timestamps
- 🔍 **Filter results** by segment type (matches, time differences, text changes, etc.)
- 🎨 **Dark theme UI** with responsive design
- 💻 **Desktop application** - no terminal required for end users

## How It Works

### Bilingual SRT Support
- Detects and separates bilingual subtitles (two languages separated by blank lines)
- Automatically identifies which block is English (can be first or second position)
- Compares only English content while preserving the second language
- Downloads merged SRT with both languages intact

### Comparison Logic
The system detects:
- **Exact matches** - same timestamp and content
- **Time differences** - same content, different timing
- **Text changes** - same timestamp, modified dialogue
- **Deleted segments** - present in base file only
- **New segments** - present in comparing file only

## Prerequisites

Before building or running the application, ensure you have the following installed:

### Required Software

1. **Python 3.11 or higher**
   - Download from: https://www.python.org/downloads/
   - Make sure to add Python to PATH during installation

2. **Node.js and npm**
   - Download from: https://nodejs.org/
   - Recommended: LTS version

3. **MongoDB**
   - Download from: https://www.mongodb.com/try/download/community
   - Install as a service or standalone

## Installation

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

### 3. Install Electron Dependencies

```bash
cd electron
npm install
cd ..
```

## 🚀 Running the Application

### Development Mode (All-in-One)

```bash
cd electron
npm start
```

This will automatically:
- ✅ Start MongoDB (if running as service)
- ✅ Start backend server on port 8000
- ✅ Start frontend dev server on port 5173
- ✅ Launch Electron desktop window

### Development Mode (Separate Components)

1. **Start MongoDB** (if not running as a service):
   ```bash
   mongod --dbpath ./data/db
   ```

2. **Start Backend**:
   ```bash
   python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
   ```

3. **Start Frontend**:
   ```bash
   cd frontend
   npm run dev
   ```

4. **Start Electron**:
   ```bash
   cd electron
   npm start
   ```

### Access the Web Application (Development)

- **Frontend UI**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

## � Building Desktop Application

### Build for Your Platform

**Windows:**
```bash
cd electron
npm run build:win
```

**macOS:**
```bash
cd electron
npm run build:mac
```

**Linux:**
```bash
cd electron
npm run build:linux
```

### Build for All Platforms

```bash
cd electron
npm run build:all
```

### Distribution Files

After building, installers will be in `electron/dist/`:

- **Windows**: `SRT Comparison Tool Setup.exe` (NSIS installer)
- **macOS**: `SRT Comparison Tool.dmg` (Disk image)
- **Linux**: `srt-comparison-app.AppImage` and `srt-comparison-app.deb`

## � Usage Guide

1. **Launch the application**
2. **Register/Login** to access the tool
3. **Upload two SRT files** (base version and comparing version)
4. **View comparison results** with detailed segment analysis:
   - Exact matches
   - Time differences
   - Text changes
   - Deleted segments
   - New segments
5. **Filter results** by clicking on summary cards
6. **Edit segments** directly in the comparison table
7. **Save changes** to database
8. **Download merged bilingual SRT** file with both languages

## 🏗️ Project Structure

```
versioning/
├── main.py                 # FastAPI backend server
├── srt_compare.py          # SRT parsing and comparison engine
├── auth.py                 # Authentication logic
├── database.py             # MongoDB connection
├── models.py               # Pydantic models
├── requirements.txt        # Python dependencies
├── frontend/               # React frontend application
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── LoginPage.jsx
│   │   │   ├── RegisterPage.jsx
│   │   │   ├── DashboardPage.jsx
│   │   │   ├── ComparisonPage.jsx
│   │   │   └── HistoryDetailPage.jsx
│   │   ├── components/
│   │   │   └── Header.jsx
│   │   ├── services/
│   │   │   └── api.js
│   │   └── context/
│   │       └── AuthContext.jsx
│   ├── package.json
│   └── vite.config.js
└── electron/               # Desktop application packaging
    ├── main.js             # Electron main process
    ├── preload.js          # Security bridge
    ├── package.json        # Electron configuration
    ├── loading.html        # Loading screen
    └── error.html          # Error screen
```

## 📦 Dependencies

### Backend (Python)
- **FastAPI** - Modern web framework
- **Uvicorn** - ASGI server
- **Motor** - Async MongoDB driver
- **PyMongo** - MongoDB driver
- **python-jose** - JWT authentication
- **passlib** - Password hashing
- **python-multipart** - File upload support
- **Pydantic** - Data validation

### Frontend (JavaScript)
- **React** 18.2.0 - UI library
- **Vite** 5.0.0 - Build tool
- **Axios** 1.6.0 - HTTP client
- **React Router DOM** 6.20.0 - Routing
- **Lucide React** 0.300.0 - Icons

### Desktop (Electron)
- **Electron** 28.0.0 - Desktop app framework
- **electron-builder** 24.9.1 - Build tool
- **electron-store** 8.1.0 - Persistent storage

## 🔧 Configuration

### Backend Configuration
Edit `main.py` to configure:
- MongoDB connection string (default: `mongodb://localhost:27017`)
- CORS settings
- Upload directory (default: `uploads/`)
- Port settings (default: 8000)

### Frontend Configuration
Edit `frontend/src/services/api.js`:
- API base URL (default: `http://localhost:8000`)
- Request timeout
- Authentication headers


## 🐛 Troubleshooting

### Application Won't Start

1. **Check MongoDB is running:**
   ```bash
   # Check MongoDB status (Linux/Mac)
   sudo systemctl status mongod
   
   # Windows - check services or start manually
   net start MongoDB
   ```

2. **Verify Python dependencies:**
   ```bash
   pip list | grep -E "fastapi|uvicorn|motor"
   ```

3. **Verify frontend dependencies:**
   ```bash
   cd frontend && npm list
   ```

4. **Check console logs** for specific errors

### Backend Errors

- **Port 8000 already in use:**
  ```bash
  # Find and kill the process
  lsof -i :8000  # Linux/Mac
  netstat -ano | findstr :8000  # Windows
  ```

- **MongoDB connection error:**
  - Ensure MongoDB is running
  - Check connection string in `database.py`
  - Verify database name: `srt_comparison`

- **Python version error:**
  ```bash
  python --version  # Should be 3.11+
  ```

### Frontend Errors

- **Port 5173 unavailable:**
  ```bash
  # Change port in vite.config.js
  server: { port: 5174 }
  ```

- **Dependency conflicts:**
  ```bash
  cd frontend
  rm -rf node_modules package-lock.json
  npm install --legacy-peer-deps
  ```

- **Build errors:**
  ```bash
  npm cache clean --force
  rm -rf node_modules package-lock.json
  npm install
  ```

### Desktop App Build Errors

- **Missing build tools:**
  - **Windows**: Install Visual Studio Build Tools
  - **macOS**: Install Xcode Command Line Tools (`xcode-select --install`)
  - **Linux**: Install `fpm` for creating .deb packages

- **electron-builder errors:**
  ```bash
  cd electron
  rm -rf node_modules package-lock.json
  npm install
  ```

- **Code signing issues (macOS):**
  - Remove or configure code signing in `electron/package.json`
  - Add `"identity": null` to skip signing in development

## 💡 Development Tips

- Use **React DevTools** browser extension for debugging frontend
- Access **FastAPI docs** at http://localhost:8000/docs for API testing
- Check **Electron console** (View → Toggle Developer Tools) for desktop app logs
- Use **MongoDB Compass** to inspect database contents
- Enable **CORS** in development, disable in production

## 🔐 Security Notes

- Change default JWT secret key in production
- Use environment variables for sensitive configuration
- Enable HTTPS in production deployment
- Implement rate limiting for API endpoints
- Validate and sanitize all file uploads

## 📝 License

This project is proprietary software. All rights reserved.

## 🤝 Support

For issues or questions, contact the development team.

### Python Import Errors
Reinstall dependencies:

```bash
pip install -r requirements.txt --force-reinstall
```

## 📝 API Endpoints

- `POST /api/auth/register` - User registration
- `POST /api/auth/login` - User login
- `GET /api/auth/me` - Get current user
- `POST /api/translate` - Upload English SRT + target language; returns bilingual SRT (translation below each segment)
- `POST /api/compare` - Compare two SRT files (versioning on English content only)
- `GET /api/comparisons` - Get comparison history
- `GET /api/comparisons/{id}` - Get specific comparison
- `GET /api/comparisons/{id}/export` - Export comparison results

## 🔐 Authentication

The application uses JWT (JSON Web Tokens) for authentication. Tokens are stored in localStorage and automatically included in API requests.

## 📄 License

This project is for internal use.
