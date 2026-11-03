from pathlib import Path
import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# Визначення шляхів до даних та артефактів
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "ames_train.csv"
ARTIFACTS = BASE_DIR / "artifacts"

# Шлях для збереження моделі (сумісний як з локальним запуском, так і з Docker)
ARTIFACT_PATH = Path("/app/artifacts/model.pkl")
if not ARTIFACT_PATH.parent.exists():
    try:
        ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        ARTIFACT_PATH = ARTIFACTS / "model.pkl"
        ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)

NUM_FEATURES = ["Gr Liv Area", "Total Bsmt SF", "Garage Area", "Year Built", "Overall Qual"]
CAT_FEATURES = ["MS Zoning"]
TARGET = "SalePrice"


def build_pipeline() -> Pipeline:
    """Побудова пайплайну передобработки даних та регресії."""
    num_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    cat_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", num_transformer, NUM_FEATURES),
            ("cat", cat_transformer, CAT_FEATURES),
        ]
    )
    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("regressor", Ridge(alpha=1.0, random_state=42)),
        ]
    )


def main() -> None:
    """Train the model, evaluate metrics, and persist the artifact."""
    df = pd.read_csv(DATA_PATH)
    df = df.dropna(subset=[TARGET])

    X = df[NUM_FEATURES + CAT_FEATURES]
    y = df[TARGET]

    # 1. Початкова оцінка In-Sample (на всіх даних — для порівняння)
    full_pipe = build_pipeline()
    full_pipe.fit(X, y)
    in_sample_preds = full_pipe.predict(X)
    in_sample_r2 = r2_score(y, in_sample_preds)
    in_sample_mae = mean_absolute_error(y, in_sample_preds)
    print(f"[train] 1. In-sample (baseline): R2={in_sample_r2:.4f}, MAE={in_sample_mae:.2f} USD")

    # 2. Розділення на навчальну (80%) та тестову (20%) вибірки (Train/Test Split)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = build_pipeline()
    model.fit(X_train, y_train)

    # Оцінка на тренувальній частині
    train_preds = model.predict(X_train)
    train_r2 = r2_score(y_train, train_preds)
    train_mae = mean_absolute_error(y_train, train_preds)

    # Оцінка на тестовій частині (Out-of-sample)
    test_preds = model.predict(X_test)
    test_r2 = r2_score(y_test, test_preds)
    test_mae = mean_absolute_error(y_test, test_preds)

    print(f"[train] 2. Train split (80%):    R2={train_r2:.4f}, MAE={train_mae:.2f} USD")
    print(f"[train] 3. Test split (20%):     R2={test_r2:.4f}, MAE={test_mae:.2f} USD")

    # 3. 5-кратна крос-валідація (5-Fold Cross-Validation)
    cv_results = cross_validate(
        build_pipeline(),
        X,
        y,
        cv=5,
        scoring=("r2", "neg_mean_absolute_error"),
    )
    cv_r2_mean = cv_results["test_r2"].mean()
    cv_r2_std = cv_results["test_r2"].std()
    cv_mae_mean = -cv_results["test_neg_mean_absolute_error"].mean()
    print(
        f"[train] 4. 5-Fold Cross-Val:     R2={cv_r2_mean:.4f} (+/- {cv_r2_std:.4f}), "
        f"MAE={cv_mae_mean:.2f} USD"
    )

    # Зберігаємо фінальну модель за допомогою joblib (як це очікується в проєкті)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, ARTIFACT_PATH)
    print(f"[train] artifact persisted: {ARTIFACT_PATH}")


if __name__ == "__main__":
    main()