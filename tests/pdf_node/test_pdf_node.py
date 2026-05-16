"""PDFNode 테스트."""

import asyncio
import tempfile
from pathlib import Path

class MockState:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


async def test_pdf_node_basic():
    """PDFNode 기본 테스트."""
    print("PDFNode 기본 테스트 시작...")
    
    try:
        from langchain_core.messages import AIMessage, HumanMessage
        print("langchain_core.messages import 성공")
        
        from proovy_agent.graph.nodes.pdf_node import PDFNode, create_pdf_node
        print("PDFNode import 성공")
        
        # 로컬 outputs 폴더 사용
        temp_path = Path("/app/outputs")
        print(f"임시 디렉토리: {temp_path}")
        
        messages = [
            HumanMessage(content="이차방정식 x² + 2x + 1 = 0을 풀어주세요", metadata={"display": "content"}),
            AIMessage(content="이 방정식은 완전제곱식입니다.\n\n1단계: 인수분해\nx² + 2x + 1 = (x + 1)² = 0\n\n2단계: 해 구하기\nx + 1 = 0\nx = -1 (중근)", metadata={"display": "content"}),
        ]
        
        test_state = MockState(
            thread_id="test_thread_123",
            user_id="test_user_456",
            messages=messages
        )
        print("Mock State 생성 성공")
        
        pdf_node = PDFNode(output_dir=temp_path)
        print("PDFNode 인스턴스 생성 성공")
        
        config_valid = pdf_node.validate_configuration()
        print(f"설정 검증 결과: {config_valid}")
        
        templates = pdf_node.get_available_templates()
        print(f"사용 가능한 템플릿: {templates}")
        
        print("\nPDFRequest 생성 테스트...")
        pdf_request = await pdf_node._create_pdf_request_from_state(test_state)
        print("PDFRequest 생성 성공")
        print(f"  thread_id: {pdf_request.thread_id}")
        print(f"  user_id: {pdf_request.user_id}")
        print(f"  섹션 수: {len(pdf_request.content_sections)}")
        print(f"  request_id: {pdf_request.request_id}")
        
        for i, section in enumerate(pdf_request.content_sections):
            print(f"    섹션 {i+1}: {section.title} ({section.content_type})")
        
        print("\nHTML → PDF 변환 테스트...")
        try:
            from proovy_agent.graph.nodes.pdf_node.pdf_generator import PDFGenerator
            
            # HTML 파일 경로 
            html_file = Path(__file__).parent / "test_result_complete.html"
            output_file = Path("/app/outputs/test_result_complete_converted.pdf")
            
            print(f"HTML 파일: {html_file}")
            print(f"출력 파일: {output_file}")
            
            # PDFGenerator로 HTML → PDF 변환
            pdf_gen = PDFGenerator()
            success = await pdf_gen.generate_pdf_from_html_file(html_file, output_file)
            
            if success:
                file_size = output_file.stat().st_size
                print(f"HTML → PDF 변환 성공!")
                print(f"파일 크기: {file_size / 1024:.1f}KB")
                print(f"저장 위치: {output_file}")
            else:
                print("HTML → PDF 변환 실패")
            
        except Exception as e:
            print(f"HTML → PDF 변환 중 예외: {e}")
            import traceback
            traceback.print_exc()
        
        
        print("\ncreate_pdf_node 팩토리 함수 테스트...")
        factory_node = create_pdf_node(output_dir=str(temp_path))
        print("팩토리 함수로 PDFNode 생성 성공")
        
        print("\n모든 기본 테스트 완료!")
            
    except ImportError as e:
        print(f"Import 오류: {e}")
        print("PYTHONPATH를 확인하거나 프로젝트 루트에서 실행해주세요")
        return False
        
    except Exception as e:
        print(f"테스트 실행 오류: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_pdf_node_basic())
    if success:
        print("\n테스트 성공!")
    else:
        print("\n테스트 실패!")
        exit(1)