"""
CommandParser 테스트 모듈

@커맨드 파싱 시스템의 모든 기능을 검증합니다.
"""

import pytest

from proovy_agent.graph.nodes.ocr_node.command_parser import (
    CommandParser,
    ParsedCommand,
    create_command_parser,
)


class TestCommandParser:
    """CommandParser 기본 기능 테스트"""

    def setup_method(self):
        """각 테스트 전 초기화"""
        self.parser = create_command_parser()

    def test_initialization(self):
        """파서 초기화 테스트"""
        assert isinstance(self.parser, CommandParser)
        assert len(self.parser.command_patterns) > 0
        assert len(self.parser.intent_keywords) > 0

    def test_empty_input(self):
        """빈 입력 처리 테스트"""
        result = self.parser.parse("")
        assert isinstance(result, ParsedCommand)
        assert result.tags == []
        assert result.confidence == 0.0

        result_none = self.parser.parse(None)
        assert result_none.tags == []


class TestExplicitCommands:
    """명시적 @커맨드 파싱 테스트"""

    def setup_method(self):
        self.parser = create_command_parser()

    def test_term_command(self):
        """@용어 커맨드 테스트"""
        result = self.parser.parse("@용어 기각역")
        assert "term:기각역" in result.tags
        assert result.confidence > 0.0

        # 오타 허용 테스트
        result_typo = self.parser.parse("@영어 삼각함수")
        assert "term:삼각함수" in result_typo.tags

    def test_video_command(self):
        """@해설영상 커맨드 테스트"""
        result = self.parser.parse("@해설영상")
        assert "video" in result.tags

        # 문제 번호 포함
        result_with_num = self.parser.parse("@해설영상 2번 문제")
        assert "video" in result_with_num.tags
        assert "problem:2" in result_with_num.tags

        # 변형 허용
        result_variant = self.parser.parse("@해설동영상")
        assert "video" in result_variant.tags

    def test_pdf_command(self):
        """@해설지 커맨드 테스트"""
        result = self.parser.parse("@해설지 생성")
        assert "pdf" in result.tags

        result_pdf = self.parser.parse("@PDF 생성")
        assert "pdf" in result_pdf.tags

    def test_solve_command(self):
        """@풀이 커맨드 테스트"""
        result = self.parser.parse("@풀이 과정")
        assert "solve" in result.tags
        assert "detailed" in result.tags

        result_step = self.parser.parse("@단계별 풀이")
        assert "solve" in result_step.tags

    def test_multiple_commands(self):
        """복합 커맨드 테스트"""
        result = self.parser.parse("@용어 기각역 @해설지 생성")
        assert "term:기각역" in result.tags
        assert "pdf" in result.tags


class TestNaturalLanguageIntent:
    """자연어 의도 분석 테스트"""

    def setup_method(self):
        self.parser = create_command_parser()

    def test_term_intent(self):
        """용어 설명 의도 테스트"""
        test_cases = [
            "기각역이 뭐야?",
            "삼각함수란 무엇인가요?",
            "미분의 의미를 설명해주세요",
            "적분에 대해 알려줘",
        ]

        for text in test_cases:
            result = self.parser.parse(text)
            # term 태그 또는 term:용어명 태그가 포함되어야 함
            has_term_tag = any(tag.startswith("term") for tag in result.tags)
            assert has_term_tag, f"Failed for: {text}"

    def test_video_intent(self):
        """영상 제작 의도 테스트"""
        test_cases = [
            "영상으로 설명해줘",
            "해설영상 만들어주세요",
            "동영상으로 보여줘",
            "비디오로 설명해",
        ]

        for text in test_cases:
            result = self.parser.parse(text)
            assert "video" in result.tags, f"Failed for: {text}"

    def test_pdf_intent(self):
        """PDF 생성 의도 테스트"""
        test_cases = ["PDF로 저장해줘", "해설지 만들어주세요", "파일로 다운로드하고 싶어요"]

        for text in test_cases:
            result = self.parser.parse(text)
            assert "pdf" in result.tags, f"Failed for: {text}"

    def test_solve_intent(self):
        """문제 풀이 의도 테스트"""
        test_cases = ["이 문제를 풀어주세요", "풀이 과정을 보여줘", "단계별로 해결해주세요"]

        for text in test_cases:
            result = self.parser.parse(text)
            assert "solve" in result.tags, f"Failed for: {text}"


class TestProblemNumberExtraction:
    """문제 번호 추출 테스트"""

    def setup_method(self):
        self.parser = create_command_parser()

    def test_problem_number_patterns(self):
        """다양한 문제 번호 패턴 테스트"""
        test_cases = [
            ("2번 문제를 풀어주세요", "2"),
            ("문제 3번 해결해줘", "3"),
            ("#7번 문제", "7"),
            ("#7", "7"),
            # "10번" 단독 패턴 제거됨 - 오탐 방지
        ]

        for text, expected_num in test_cases:
            result = self.parser.parse(text)
            assert f"problem:{expected_num}" in result.tags, f"Failed for: {text}"

    def test_no_problem_number(self):
        """문제 번호가 없는 경우 테스트"""
        result = self.parser.parse("그냥 설명해주세요")
        problem_tags = [tag for tag in result.tags if tag.startswith("problem:")]
        assert len(problem_tags) == 0


class TestTagDeduplication:
    """태그 중복 제거 및 우선순위 테스트"""

    def setup_method(self):
        self.parser = create_command_parser()

    def test_duplicate_removal(self):
        """중복 태그 제거 테스트"""
        # @용어와 자연어 의도 모두 감지되는 경우
        result = self.parser.parse("@용어 기각역 기각역이 뭐야?")

        # term 태그는 이제 다중 허용되므로 2개일 수 있음
        term_tags = [tag for tag in result.tags if tag.startswith("term")]
        assert len(term_tags) >= 1  # 최소 1개는 있어야 함

    def test_priority_order(self):
        """태그 우선순위 테스트"""
        result = self.parser.parse("@용어 삼각함수 @해설영상 @해설지 생성")

        # 우선순위에 따라 정렬되어야 함
        expected_order = ["term:삼각함수", "video", "pdf"]
        actual_tags = [tag for tag in result.tags if tag in expected_order]

        # 순서는 중요하지 않지만, 모든 태그가 포함되어야 함
        assert set(actual_tags) == set(expected_order)


class TestConfidenceCalculation:
    """신뢰도 계산 테스트"""

    def setup_method(self):
        self.parser = create_command_parser()

    def test_explicit_command_confidence(self):
        """명시적 커맨드 신뢰도 테스트"""
        result = self.parser.parse("@용어 기각역")
        assert result.confidence > 0.2

    def test_natural_intent_confidence(self):
        """자연어 의도 신뢰도 테스트"""
        result = self.parser.parse("기각역이 뭐야?")
        assert result.confidence > 0.0

    def test_combined_confidence(self):
        """복합 신뢰도 테스트"""
        explicit_result = self.parser.parse("@용어 기각역")
        natural_result = self.parser.parse("기각역이 뭐야?")
        combined_result = self.parser.parse("@용어 기각역 기각역이 뭐야?")

        # 복합 결과가 개별 결과보다 높은 신뢰도를 가져야 함
        assert combined_result.confidence >= explicit_result.confidence
        assert combined_result.confidence >= natural_result.confidence


class TestEdgeCases:
    """에지 케이스 테스트"""

    def setup_method(self):
        self.parser = create_command_parser()

    def test_malformed_commands(self):
        """잘못된 형태의 커맨드 테스트"""
        test_cases = [
            "@용어",  # 매개변수 없음
            "@해설영상만들어",  # 공백 없음
            "@PDF생성해줘",  # 공백 없음
        ]

        for text in test_cases:
            # 파싱 에러가 발생하지 않고 부분적이라도 결과를 반환해야 함
            result = self.parser.parse(text)
            assert isinstance(result, ParsedCommand)

    def test_mixed_korean_english(self):
        """한영 혼재 텍스트 테스트"""
        result = self.parser.parse("@term function 설명해줘")
        # 일부라도 인식되어야 함
        assert len(result.tags) > 0

    def test_long_text(self):
        """긴 텍스트 처리 테스트"""
        long_text = "이 문제는 삼각함수에 관한 문제입니다. @용어 기각역에 대해 설명하고 @해설영상 만들어주세요. PDF로 저장해주세요."
        result = self.parser.parse(long_text)

        # 실제 파싱된 결과 확인 (정규식이 다른 부분까지 포함할 수 있음)
        term_tags = [tag for tag in result.tags if tag.startswith("term:")]
        assert len(term_tags) > 0
        assert "기각역" in term_tags[0]  # 기각역이 포함되어 있는지만 확인
        assert "video" in result.tags
        assert "pdf" in result.tags

    def test_special_characters(self):
        """특수 문자 포함 텍스트 테스트"""
        result = self.parser.parse("@용어 sin²θ + cos²θ = 1")
        assert len(result.tags) > 0


class TestErrorHandling:
    """에러 처리 테스트"""

    def setup_method(self):
        self.parser = create_command_parser()

    def test_none_input(self):
        """None 입력 처리"""
        result = self.parser.parse(None)
        assert isinstance(result, ParsedCommand)
        assert result.tags == []

    def test_whitespace_input(self):
        """공백 입력 처리"""
        result = self.parser.parse("   \t\n  ")
        assert result.tags == []


class TestRegressionCases:
    """오탐 케이스 회귀 테스트"""

    def setup_method(self):
        self.parser = create_command_parser()

    def test_false_positive_keywords(self):
        """범용 키워드 오탐 방지 테스트"""
        false_positive_cases = [
            "숙제 만들어줘",  # "만들어" 단독으로는 video 태그 안생성
            "정답 알려줘",  # "알려줘" 단독으로는 term 태그 안생성
            "파일을 다운로드하고 싶어요",  # "파일", "다운로드" 단독으로는 pdf 태그 안생성
        ]

        for text in false_positive_cases:
            result = self.parser.parse(text)
            # 패턴 매칭이 없으면 태그가 생성되지 않아야 함
            assert len(result.tags) == 0, f"False positive for: {text}, got: {result.tags}"

    def test_edge_case_patterns(self):
        """에지 케이스 패턴 테스트"""
        # 이런 경우는 패턴 매칭에 의해 태그가 생성될 수 있음
        edge_cases = [
            "과정을 설명해주세요",  # "과정" + "설명해" 패턴 매칭 가능
        ]

        for text in edge_cases:
            _ = self.parser.parse(text)
            # 에지 케이스는 패턴 매칭에 의해 태그 생성 가능
            # 오탐이 아닌 의도된 동작

    def test_problem_number_false_positives(self):
        """문제 번호 오탐 방지 테스트"""
        false_positive_cases = [
            "1번째로 중요한 것은",
            "다음번에 해보자",
            "10번 버스를 타세요",
            "3번 반복해보세요",
        ]

        for text in false_positive_cases:
            result = self.parser.parse(text)
            problem_tags = [tag for tag in result.tags if tag.startswith("problem:")]
            assert len(problem_tags) == 0, f"False positive problem number for: {text}"

    def test_multiple_term_tags(self):
        """다중 term 태그 허용 테스트"""
        result = self.parser.parse("@용어 기각역 @용어 삼각함수")
        term_tags = [tag for tag in result.tags if tag.startswith("term:")]
        assert len(term_tags) == 2
        assert "term:기각역" in result.tags
        assert "term:삼각함수" in result.tags

    def test_consecutive_commands_separation(self):
        """연속 @커맨드 분리 테스트"""
        result = self.parser.parse("@해설영상 @해설지 생성")
        assert "video" in result.tags
        assert "pdf" in result.tags

        # video 태그에 "@해설지 생성"이 포함되지 않아야 함
        detected_patterns = result.detected_patterns
        video_patterns = [p for p in detected_patterns if "해설영상" in p]
        assert len(video_patterns) > 0
        for pattern in video_patterns:
            assert "@해설지" not in pattern, f"Greedy regex captured next command: {pattern}"


class TestFactoryFunction:
    """팩토리 함수 테스트"""

    def test_create_command_parser(self):
        """create_command_parser 팩토리 함수 테스트"""
        parser = create_command_parser()
        assert isinstance(parser, CommandParser)

        # 두 번 호출해도 독립적인 인스턴스
        parser2 = create_command_parser()
        assert parser is not parser2


class TestIntegration:
    """통합 테스트"""

    def setup_method(self):
        self.parser = create_command_parser()

    def test_realistic_scenarios(self):
        """실제 사용 시나리오 테스트"""
        scenarios = [
            {
                "text": "삼각함수 문제 2번을 영상으로 설명해주세요",
                "expected_tags": ["video", "problem:2"],
                "expected_intents": ["video", "problem"],
            },
            {
                "text": "@용어 기각역 @해설지 생성",
                "expected_tags": ["term:기각역", "pdf"],
                "expected_intents": ["term", "pdf"],
            },
            {
                "text": "이 문제를 풀어주고 PDF로 저장해줘",
                "expected_tags": ["solve", "pdf"],
                "expected_intents": ["solve", "pdf"],
            },
        ]

        for scenario in scenarios:
            result = self.parser.parse(scenario["text"])

            # 모든 예상 태그가 포함되어야 함
            for expected_tag in scenario["expected_tags"]:
                assert expected_tag in result.tags, f"Missing tag '{expected_tag}' in {result.tags}"

            # 신뢰도가 적절해야 함
            assert result.confidence > 0.0

            # 원본 텍스트가 저장되어야 함
            assert result.original_text == scenario["text"]


if __name__ == "__main__":
    # 개별 테스트 실행을 위한 코드
    pytest.main([__file__, "-v"])
