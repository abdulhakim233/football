import os
import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import JWTError, jwt

# --- Load Environment Variable ---
RAW_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./football.db")

# Format database URL for SQLAlchemy + PyMySQL
connect_args = {}
db_url = RAW_DATABASE_URL

if RAW_DATABASE_URL.startswith("mysql://") or RAW_DATABASE_URL.startswith("mysql+pymysql://"):
    # Ensure driver is pymysql
    if RAW_DATABASE_URL.startswith("mysql://"):
        db_url = RAW_DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)

    # Clean URL parameters and enable SSL for cloud providers like Aiven
    if "?" in db_url:
        base_url, query_str = db_url.split("?", 1)
        db_url = base_url
    
    connect_args = {
        "ssl": {
            "ssl_mode": "REQUIRED"
        }
    }
elif "sqlite" in RAW_DATABASE_URL:
    connect_args = {"check_same_thread": False}

# Initialize Engine with fallback to local SQLite if remote host is still provisioning
try:
    engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
except Exception as e:
    print(f"Warning: Primary database connection error ({e}). Falling back to SQLite.")
    engine = create_engine("sqlite:///./football.db", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()

SECRET_KEY = os.getenv("SECRET_KEY", "football-shuffler-secret-key-prod-992")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# --- Database Models ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class GameSession(Base):
    __tablename__ = "game_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(150), default="Weekly Match")
    state_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

try:
    Base.metadata.create_all(bind=engine)
except Exception as err:
    print(f"Notice: Initial create_all deferred or running on fallback ({err}).")

# --- Schemas ---
class UserRegister(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut

class StatePayload(BaseModel):
    state_json: str

# --- Helper Functions ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None):
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + (expires_delta or datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# --- FastAPI App ---
app = FastAPI(title="Football Shuffler API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.responses import HTMLResponse, FileResponse

# Root fallback to serve index.html directly from FastAPI if needed
@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "index.html")
    if not os.path.exists(index_path):
        index_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Football Shuffler</h1>"


# --- Auth Routes ---
@app.post("/api/auth/register", response_model=Token)
def register(user_in: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == user_in.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username is already taken.")
    
    hashed = get_password_hash(user_in.password)
    new_user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=hashed
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token = create_access_token(data={"sub": new_user.username})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": new_user.id, "username": new_user.username, "email": new_user.email}
    }

@app.post("/api/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = create_access_token(data={"sub": user.username})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "username": user.username, "email": user.email}
    }

@app.get("/api/auth/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username, "email": current_user.email}

# --- User Cloud Sync Routes ---
@app.get("/api/game-data")
def load_game_data(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(GameSession).filter(GameSession.user_id == current_user.id).first()
    if not record:
        return {"state_json": None}
    return {"state_json": record.state_json, "updated_at": record.updated_at}

@app.post("/api/game-data")
def save_game_data(payload: StatePayload, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(GameSession).filter(GameSession.user_id == current_user.id).first()
    if not record:
        record = GameSession(user_id=current_user.id, state_json=payload.state_json)
        db.add(record)
    else:
        record.state_json = payload.state_json
        record.updated_at = datetime.datetime.utcnow()
    db.commit()
    return {"status": "saved"}

# --- View All Saved Data (Admin/Inspector Dashboard) ---
@app.get("/api/admin/overview")
def view_database_overview(db: Session = Depends(get_db)):
    users = db.query(User).all()
    sessions = db.query(GameSession).all()
    
    users_data = []
    for u in users:
        sess = next((s for s in sessions if s.user_id == u.id), None)
        parsed_state = None
        if sess and sess.state_json:
            try:
                import json
                parsed_state = json.loads(sess.state_json)
            except Exception:
                parsed_state = sess.state_json

        users_data.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "registered_at": u.created_at,
            "has_saved_game": sess is not None,
            "last_updated": sess.updated_at if sess else None,
            "game_summary": {
                "player_count": len(parsed_state.get("players", [])) if isinstance(parsed_state, dict) else 0,
                "team_count": len(parsed_state.get("teams", [])) if isinstance(parsed_state, dict) else 0,
                "current_game_number": parsed_state.get("gameNumber", 1) if isinstance(parsed_state, dict) else 1,
                "data": parsed_state
            } if parsed_state else None
        })

    return {
        "database_engine": engine.name,
        "total_users": len(users),
        "total_sessions": len(sessions),
        "users": users_data
    }

