# OCR 노드 아키텍처 설계

> **상태**: 설계 중  
> **목적**: LangGraph 기반 수학 문제 풀이 에이전트에서 이미지/파일 입력을 텍스트로 변환하고 @커맨드를 파싱하는 OCR 노드의 완전한 아키텍처 설계  
> **최종 업데이트**: 2026-06-01

## 개요

OCR 노드는 현재 `preprocessor.py`에서 수행하는 단순한 텍스트 파싱을 대체하여, **VLM 기반 고도화된 OCR + @커맨드 파싱 시스템**을 제공합니다.

### 현재 Preprocessor 한계점
```python
# 현재 preprocessor.py 구현
async def preprocessor(state: ProovyState) -> dict:
    problem = state.raw_input.get("problem", "")
    tags = re.findall(r"@\S+", problem)  # 단순 정규식
    clean_text = re.sub(r"@\S+", "", problem).strip()
    return {
        "ocr_text": clean_text or problem,
        "ocr_confidence": 1.0,  # 하드코딩
        "tags": tags,
    }
```

**문제점**:
- 이미지 입력 처리 불가
- PDF 파일 지원 없음  
- @커맨드 컨텍스트 이해 부족
- 수학 수식 인식 불가
- 다국어 지원 없음

## 요구사항 분석

### 1. 기능적 요구사항

#### 1.1 입력 처리
- **이미지 형식**: PNG, JPG, JPEG, WebP
- **문서 형식**: PDF (다중 페이지)
- **텍스트 형식**: 기존 텍스트 입력 유지
- **크기 제한**: 개별 이미지 10MB, PDF 50MB
- **해상도**: 최대 4096x4096px

#### 1.2 OCR 엔진
- **주 엔진**: Google Gemini 2.5 Flash (VLM)
- **보조 엔진**: Gemini 1.5 Pro-002 (복잡한 수학 수식용)
- **폴백**: Claude Sonnet 4.5 (Gemini 실패 시)

#### 1.3 출력 형식
```python
class OCRResult(BaseModel):
    extracted_text: str              # 통합된 텍스트
    confidence: float               # 전체 신뢰도 (0.0-1.0)
    command_tags: list[CommandTag]   # 파싱된 @커맨드들
    math_expressions: list[MathExpression]  # 수식들
    pages: list[PageResult] | None   # PDF용 페이지별 결과
    language: str                   # 감지된 언어 ('ko', 'en', 'mixed')
    processing_metadata: ProcessingMetadata
```

#### 1.4 @커맨드 파싱
- **기본 커맨드**: `@해설영상`, `@해설지`, `@단계별`, `@빠른풀이`
- **자연어 변환**: "영상으로 만들어줘" → `@해설영상` 
- **컨텍스트 추론**: 문장에서 의도 파악

### 2. 비기능적 요구사항

#### 2.1 성능
- **목표 처리 시간**: 
  - 단일 이미지: 3초 이내
  - PDF (5페이지): 10초 이내
- **동시 처리**: 최대 5개 요청
- **메모리**: 요청당 최대 500MB

#### 2.2 정확도
- **텍스트 인식**: 95% 이상
- **수학 수식**: 90% 이상  
- **@커맨드 파싱**: 98% 이상

#### 2.3 안정성
- **오류 처리**: Graceful degradation
- **폴백 체계**: VLM 실패 시 단계별 대안
- **재시도**: 일시적 오류 3회 재시도

## 아키텍처 설계

### 1. 전체 구조

```
OCR Node (Preprocessor 대체)
├── FileProcessor          # 파일/이미지 전처리
├── VLMProcessor          # VLM 기반 OCR  
├── CommandParser         # @커맨드 파싱
├── LanguageDetector      # 언어 감지
├── QualityAssessment     # 품질 평가
└── ResultAggregator      # 결과 통합
```

### 2. 상세 컴포넌트

#### 2.1 FileProcessor
**책임**: 다양한 입력 형식을 통일된 이미지로 변환

```python
class FileProcessor:
    async def process_input(self, raw_input: dict) -> list[ProcessedImage]:
        """
        - PDF → 페이지별 이미지 분할 (pdf2image)
        - 이미지 → 전처리 (해상도, 회전, 품질 향상)
        - 텍스트 → 이미지 없이 직접 전달
        """
        
    async def preprocess_image(self, image: PIL.Image) -> ProcessedImage:
        """
        - 해상도 최적화 (300 DPI 목표)
        - 자동 회전 보정
        - 노이즈 제거
        - 대비 향상
        """
```

**PDF 처리 전략**:
- `pdf2image` + `poppler` 사용
- 페이지당 별도 OCR 수행
- 구조화된 출력: `{page1: {...}, page2: {...}}`

#### 2.2 VLMProcessor  
**책임**: VLM을 이용한 이미지-텍스트 변환

```python
class VLMProcessor:
    def __init__(self):
        self.primary_model = "google/gemini-2.5-flash"
        self.fallback_model = "anthropic/claude-sonnet-4-5"
        
    async def extract_text(self, image: ProcessedImage, language: str) -> VLMResult:
        """
        VLM 프롬프트:
        - 수학 수식은 LaTeX 형식으로 변환  
        - 표/그래프는 구조화된 텍스트로
        - @커맨드 유지하여 추출
        """
```

**VLM 프롬프트 설계**:
```
당신은 수학 문제 이미지를 정확히 텍스트로 변환하는 전문가입니다.

규칙:
1. 수학 수식은 LaTeX 형식으로 변환하세요 ($...$, $$...$$)
2. @로 시작하는 명령어는 정확히 보존하세요
3. 표나 그래프는 구조화된 텍스트로 설명하세요
4. 한글과 영어가 섞여있다면 언어를 유지하세요

이미지에서 텍스트를 추출하세요:
```

#### 2.3 CommandParser
**책임**: 자연어와 명시적 @커맨드 파싱

```python
class CommandParser:
    EXPLICIT_COMMANDS = {
        "@해설영상": "video",
        "@해설지": "pdf", 
        "@단계별": "step_by_step",
        "@빠른풀이": "quick_solve"
    }
    
    async def parse_commands(self, text: str) -> list[CommandTag]:
        """
        1. 명시적 @커맨드 추출
        2. 자연어 의도 분석 (LLM 사용)
        3. 컨텍스트 기반 우선순위 결정
        """
```

**자연어 → 커맨드 변환**:
```python
INTENT_PATTERNS = {
    "영상": ["video"],
    "동영상": ["video"], 
    "해설 영상": ["video"],
    "PDF": ["pdf"],
    "해설지": ["pdf"],
    "단계별": ["step_by_step"],
    "자세히": ["step_by_step"],
}
```

#### 2.4 LanguageDetector
**책임**: 텍스트 언어 자동 감지

```python
class LanguageDetector:
    async def detect_language(self, text: str) -> LanguageResult:
        """
        - 한글/영어/혼합 감지
        - 수학 기호 비율 계산  
        - VLM 성능 최적화용 언어 정보 제공
        """
```

#### 2.5 QualityAssessment
**책임**: OCR 결과 품질 평가 및 재처리 결정

```python
class QualityAssessment:
    async def assess_quality(self, result: VLMResult, image: ProcessedImage) -> QualityReport:
        """
        - 신뢰도 점수 계산
        - 수식 완성도 검사
        - 재처리 필요성 판단
        """
        
    QUALITY_THRESHOLDS = {
        "min_confidence": 0.7,
        "min_math_completeness": 0.8,
        "max_unknown_chars": 0.05
    }
```

### 3. 데이터 모델

#### 3.1 핵심 모델

```python
class OCRRequest(BaseModel):
    """OCR 처리 요청"""
    raw_input: dict  # state.raw_input과 동일  
    user_id: str
    thread_id: str
    options: OCROptions = Field(default_factory=OCROptions)

class OCROptions(BaseModel):
    """OCR 처리 옵션"""
    target_language: str = "auto"  # 'ko', 'en', 'auto'
    enable_math_mode: bool = True
    enable_command_parsing: bool = True  
    quality_threshold: float = 0.7
    max_processing_time: float = 30.0
    
class ProcessedImage(BaseModel):
    """전처리된 이미지 정보"""
    image_data: bytes
    format: str
    width: int
    height: int
    dpi: int
    preprocessing_applied: list[str]

class VLMResult(BaseModel):
    """VLM 처리 결과"""
    model_name: str
    raw_text: str
    confidence: float
    processing_time: float
    token_usage: dict[str, int]

class CommandTag(BaseModel):
    """파싱된 커맨드"""
    command: str          # 'video', 'pdf', 'step_by_step'
    original_text: str    # '@해설영상' 또는 '영상으로 만들어줘'
    confidence: float     # 파싱 신뢰도
    position: int         # 텍스트 내 위치

class MathExpression(BaseModel):
    """수학 수식"""
    latex: str           # LaTeX 형식
    original: str        # 원본 텍스트
    position: tuple[int, int]  # 시작, 끝 위치
    
class PageResult(BaseModel):
    """PDF 페이지별 결과"""
    page_number: int
    text: str
    confidence: float
    math_expressions: list[MathExpression]
    
class ProcessingMetadata(BaseModel):
    """처리 메타데이터"""
    total_processing_time: float
    model_used: str
    fallback_used: bool
    pages_processed: int
    quality_score: float
    language_detected: str
```

#### 3.2 State 필드 확장

기존 `ProovyState`에 OCR 관련 필드 추가:

```python
class ProovyState(BaseModel):
    # 기존 필드들...
    
    # OCR 확장 필드 (preprocessor 대체)
    ocr_text: str = ""
    ocr_confidence: float = 0.0
    tags: list[str] = Field(default_factory=list)
    
    # 새로 추가
    ocr_result: OCRResult | None = None          # 전체 OCR 결과
    detected_language: str = "unknown"           # 감지된 언어
    math_expressions: list[MathExpression] = Field(default_factory=list)
    command_tags: list[CommandTag] = Field(default_factory=list)
    processing_metadata: ProcessingMetadata | None = None
```

### 4. 예외 처리 체계

```python
class OCRError(Exception):
    """OCR 기본 예외"""
    
class ImageProcessingError(OCRError):
    """이미지 전처리 실패"""
    
class VLMProcessingError(OCRError):
    """VLM 처리 실패"""
    
class FileConversionError(OCRError):
    """파일 변환 실패"""
    
class QualityThresholdError(OCRError):
    """품질 기준 미달"""
    
class LanguageDetectionError(OCRError):
    """언어 감지 실패"""
    
class CommandParsingError(OCRError):
    """커맨드 파싱 실패"""
```

## 구현 전략

### 1. 단계별 개발 계획

#### Phase 1: 기본 VLM OCR (1주)
- FileProcessor 기본 구현
- VLMProcessor Gemini 2.5 Flash 연동
- 단일 이미지 처리
- 기존 preprocessor 대체

#### Phase 2: PDF 및 다중 페이지 (1주)  
- PDF 페이지 분할 처리
- 페이지별 구조화된 출력
- 메모리 최적화

#### Phase 3: 고도화된 @커맨드 파싱 (1주)
- 자연어 의도 분석
- LLM 기반 커맨드 추론
- 컨텍스트 우선순위

#### Phase 4: 품질 향상 및 최적화 (1주)
- 다중 VLM 폴백
- 품질 평가 시스템
- 성능 튜닝

### 2. LangGraph 통합

#### 2.1 Builder 수정
```python
# builder.py에서 preprocessor → ocr_node 대체
from proovy_agent.graph.nodes.ocr_node import OCRNode

builder.add_node("ocr_node", OCRNode())
builder.add_edge(START, "ocr_node")
builder.add_edge("ocr_node", "router")
```

#### 2.2 Router 수정  
```python
# router.py에서 ocr_result 활용
async def router(state: ProovyState) -> dict:
    # state.ocr_result.command_tags 확인
    # 이미지 포함 여부로 use_page 결정
```

### 3. 의존성 관리

#### 3.1 새로운 의존성
```toml
# pyproject.toml 추가
dependencies = [
    # 기존 의존성들...
    "pdf2image>=3.1.0",      # PDF → 이미지 변환
    "pillow>=10.0.0",        # 이미지 처리
    "opencv-python>=4.8.0",  # 이미지 전처리
    "poppler-utils",         # PDF 처리 (시스템 의존성)
]
```

#### 3.2 Docker 이미지 수정
```dockerfile
# Dockerfile에 추가
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
```

### 4. 성능 최적화

#### 4.1 비동기 처리
```python
class OCRNode:
    async def __call__(self, state: ProovyState) -> dict:
        # PDF 페이지들을 병렬 처리
        tasks = [self._process_page(page) for page in pages]
        results = await asyncio.gather(*tasks, return_exceptions=True)
```

#### 4.2 캐싱 전략  
```python
class VLMProcessor:
    def __init__(self):
        self._cache = {}  # 이미지 해시 기반 결과 캐싱
        
    async def extract_text(self, image: ProcessedImage) -> VLMResult:
        image_hash = hashlib.sha256(image.image_data).hexdigest()
        if image_hash in self._cache:
            return self._cache[image_hash]
```

## 테스트 전략

### 1. 단위 테스트

```python
class TestFileProcessor:
    async def test_pdf_conversion(self):
        # PDF → 이미지 변환 테스트
        
    async def test_image_preprocessing(self):
        # 이미지 전처리 파이프라인 테스트

class TestVLMProcessor:
    async def test_math_formula_extraction(self):
        # 수학 수식 인식 테스트
        
    async def test_fallback_mechanism(self):
        # VLM 폴백 테스트

class TestCommandParser:
    async def test_explicit_commands(self):
        # @커맨드 파싱 테스트
        
    async def test_natural_language_intent(self):
        # 자연어 의도 분석 테스트
```

### 2. 통합 테스트

```python
class TestOCRNodeIntegration:
    async def test_full_pipeline(self):
        # 전체 파이프라인 E2E 테스트
        
    async def test_state_integration(self):
        # LangGraph State 통합 테스트
        
    async def test_performance_benchmarks(self):
        # 성능 기준 테스트
```

### 3. 실제 데이터 테스트

- 수학 교과서 이미지 샘플
- 손글씨 수학 문제
- 복잡한 수식이 포함된 PDF
- 한글/영어 혼재 문서

## 모니터링 및 운영

### 1. 메트릭스

```python
# 처리 시간 추적
PROCESSING_TIME_HISTOGRAM = Histogram(
    'ocr_processing_duration_seconds',
    'OCR processing time',
    ['model', 'input_type']
)

# 정확도 추적  
OCR_ACCURACY_GAUGE = Gauge(
    'ocr_accuracy_score',
    'OCR accuracy score',
    ['model', 'language']
)

# 실패율 추적
OCR_FAILURE_COUNTER = Counter(
    'ocr_failures_total',
    'OCR processing failures',
    ['error_type', 'model']
)
```

### 2. 로깅

```python
logger = logging.getLogger(__name__)

# 구조화된 로그
logger.info(
    "OCR processing completed",
    extra={
        "user_id": request.user_id,
        "processing_time": metadata.total_processing_time,
        "model_used": metadata.model_used,
        "confidence": result.confidence,
        "pages_processed": len(result.pages) if result.pages else 1
    }
)
```

### 3. 경보 설정

- 처리 시간 > 30초
- 정확도 < 85% (24시간 평균)
- 실패율 > 5% (1시간 평균)
- VLM API 에러율 > 10%

## 마이그레이션 계획

### 1. 기존 코드 영향도

#### 1.1 수정 필요
- `builder.py`: preprocessor → ocr_node 교체
- `router.py`: 새로운 state 필드 활용
- `state.py`: OCR 관련 필드 확장

#### 1.2 호환성 유지
- `state.ocr_text`, `state.tags` 기존 인터페이스 유지
- 기존 텍스트 입력 완전 호환

### 2. 배포 전략

#### Phase A: 병렬 배포
- OCR 노드 추가하되 기존 preprocessor 유지
- A/B 테스트로 점진적 전환

#### Phase B: 완전 전환
- preprocessor 제거
- OCR 노드로 완전 교체

#### Phase C: 최적화
- 성능 데이터 기반 튜닝
- 고도화된 기능 추가

## 결론 및 다음 단계

### 성공 기준
- ✅ 텍스트 인식 정확도 95% 이상
- ✅ 수학 수식 인식 정확도 90% 이상  
- ✅ @커맨드 파싱 정확도 98% 이상
- ✅ 처리 시간 목표 달성
- ✅ 기존 워크플로우 완전 호환

### 위험 요소 및 대응
- **VLM API 불안정성** → 다중 폴백 체계
- **처리 시간 초과** → 타임아웃 및 품질 조절
- **메모리 사용량** → 스트리밍 처리 및 캐싱
- **비용 증가** → 캐싱 및 효율적 모델 선택

### 다음 단계
1. **Phase 1 개발 시작**: 기본 VLM OCR 구현
2. **Docker 환경 구성**: 의존성 설치 및 테스트
3. **성능 벤치마크**: 실제 데이터로 기준선 설정
4. **점진적 배포**: A/B 테스트를 통한 안전한 전환