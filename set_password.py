import getpass
import pathlib
import os

def main():
    print("=========================================")
    print("🔑 Supabase Database Password Setup Helper")
    print("=========================================")
    print("Supabase에서 새로 변경하신 비밀번호를 입력해 주세요.")
    print("(입력 시 보안을 위해 비밀번호가 화면에 표시되지 않습니다)")
    
    password = getpass.getpass("비밀번호 입력: ")
    password = password.strip()
    
    if not password:
        print("❌ 입력된 비밀번호가 없습니다. 종료합니다.")
        return
        
    env_path = pathlib.Path(".env")
    if not env_path.exists():
        print("❌ .env 파일을 찾을 수 없습니다.")
        return
        
    content = env_path.read_text(encoding="utf-8")
    
    # [비밀번호] 플레이스홀더를 변경한 비밀번호로 치환
    if "[비밀번호]" in content:
        new_content = content.replace("[비밀번호]", password)
        env_path.write_text(new_content, encoding="utf-8")
        print("✅ .env 파일에 비밀번호가 성공적으로 저장되었습니다!")
    else:
        # 혹시 이미 플레이스홀더가 유실된 경우를 대비해 기존 SUPABASE_DB_URL 교체
        lines = content.splitlines()
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith("SUPABASE_DB_URL="):
                lines[i] = f"SUPABASE_DB_URL=postgresql://postgres:{password}@db.efxofhbbaokmhuilfgui.supabase.co:5432/postgres"
                replaced = True
                break
        if replaced:
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print("✅ .env 파일의 SUPABASE_DB_URL이 성공적으로 업데이트되었습니다!")
        else:
            print("❌ .env 내에 SUPABASE_DB_URL 템플릿을 찾을 수 없습니다.")
            
    # 스크립트 본인 삭제 (보안 및 흔적 지우기)
    try:
        os.remove(__file__)
    except Exception:
        pass

if __name__ == "__main__":
    main()
