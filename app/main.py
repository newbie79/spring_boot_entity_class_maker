import mariadb
import os
import re
import json
from app.utilities.settings import settings

# DB에서 테이블 정보 가져오기
def fetch_table_info(db_cursor):
    cursor.execute("""
        SELECT TABLE_NAME, TABLE_COMMENT 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = %s
        ORDER BY TABLE_NAME ASC;
    """, (settings.DB_DATABASE,))
    return {row[0]: row[1] for row in db_cursor.fetchall()}

# DB에서 컬럼 정보 가져오기
def fetch_column_info(db_cursor):
    db_cursor.execute("""
        SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT, TABLE_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_SCHEMA = %s 
        ORDER BY TABLE_NAME ASC, ORDINAL_POSITION ASC;    
    """, (settings.DB_DATABASE,))
    return db_cursor.fetchall()

def to_camel_case(snake_str):
    components = snake_str.split('_')
    return components[0].lower() + ''.join(x.capitalize() for x in components[1:])

def ends_with_number(s):
    return bool(re.search(r'\d$', s))

def load_json_to_dict(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return None

# 데이터베이스 연결 설정
DB_CONFIG = {
    "host": settings.DB_SERVER,  # MariaDB 서버 주소
    "port": settings.DB_PORT,
    "user": settings.DB_USERNAME,
    "password": settings.DB_PASSWORD,
    "database": settings.DB_DATABASE,
}

OUTPUT_DIR = "..\\output"  # 생성된 엔티티 클래스 저장 폴더
FIXED_TABLE_JSON_FILE = "..\\fixed_table_name.json"  # 오류 테이블명 JSON 파일
IS_ENTITY_CLASS = True  # JPA 엔티티 클래스 생성 여부 (False일 경우 DTO 생성)

# 데이터베이스 연결
try:
    conn = mariadb.connect(**DB_CONFIG)
    cursor = conn.cursor()
except mariadb.Error as e:
    print(f"Error connecting to MariaDB: {e}")
    exit(1)

# 테이블 목록 가져오기
db_tables = fetch_table_info(cursor)

# 컬럼 목록 가져오기
db_columns = fetch_column_info(cursor)

cursor.close()
conn.close()

fixed_table_prefix = load_json_to_dict(FIXED_TABLE_JSON_FILE)

# 각 테이블에 대한 엔티티 클래스 생성
for table_name in db_tables:
    # 숫자로 끝나는 테이블 제거
    if ends_with_number(table_name):
        continue

    table_comment = db_tables[table_name] if db_tables[table_name] else ""

    # 테이블명 접두어 보정
    table_name_arr = table_name.lower().split('_')
    if fixed_table_prefix:
        text = fixed_table_prefix.get(table_name_arr[0], "")
        if text:
            table_name_arr[0] = text

    class_name = ''.join(x.capitalize() for x in table_name_arr)  # 클래스명은 파스칼 케이스로 변환
    folder_name = table_name_arr[0]  # 테이블명에서 _ 앞의 부분을 폴더명으로 사용
    folder_path = os.path.join(OUTPUT_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    package_name = f"{settings.BASE_PACKAGE}.{folder_name}"
    file_path = os.path.join(folder_path, f"{class_name}.java")

    columns = [col for col in db_columns if col[7] == table_name]

    primary_keys = [col[0] for col in columns if col[3] == "PRI"]
    has_composite_key = IS_ENTITY_CLASS and len(primary_keys) > 1

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"package {package_name};\n\n")
        if IS_ENTITY_CLASS:
            f.write("import lombok.*;\n")
            f.write("import javax.persistence.*;\n")
            if has_composite_key:
                f.write("import java.io.Serializable;\n")
        else:
            f.write("import lombok.Data;\n")
            f.write("import lombok.NoArgsConstructor;\n")
            f.write("import lombok.AllArgsConstructor;\n")
        f.write("\n")

        # 테이블 설명 추가
        if table_comment:
            f.write(f"/** {table_comment} */\n")

        if IS_ENTITY_CLASS:
            if has_composite_key:
                f.write("@IdClass({}PK.class)\n".format(class_name))
            f.write("@Entity\n")
            f.write(f"@Table(name = \"{table_name}\")\n")
        f.write("@Data\n")
        f.write("@NoArgsConstructor\n")
        f.write("@AllArgsConstructor\n")
        f.write(f"public class {class_name} {{\n\n")

        for column in columns:
            col_name, col_type, nullable, key, default, extra, column_comment, dummy_table_name = column
            field_name = to_camel_case(col_name)  # 필드명을 카멜케이스로 변환
            field_type = "String"  # 기본적으로 문자열로 처리

            if "bigint" in col_type:
                field_type = "Long"
            elif "tinyint" in col_type:
                field_type = "Boolean"
            elif "int" in col_type or "mediumint" in col_type:
                field_type = "Integer"
            elif "double" in col_type or "float" in col_type:
                field_type = "Double"
            elif "decimal" in col_type:
                if not IS_ENTITY_CLASS and col_type.endswith(",0)"):
                    field_type = "Long"
                else:
                    field_type = "java.math.BigDecimal"
            elif "timestamp" in col_type or "datetime" in col_type:
                field_type = "java.time.LocalDateTime"
            elif "date" in col_type:
                field_type = "java.time.LocalDate"
            elif "varchar" in col_type or "text" in col_type or "char" in col_type or "mediumtext" in col_type or "longtext" in col_type:
                field_type = "String"
            else:
                raise TypeError(f"Unsupported data type: {table_name}.{col_name} {col_type}")

            # 주석 추가
            f.write(f"    /** {column_comment if column_comment else col_type} */\n")
            # f.write(f"    /* (Nullable: {nullable}, Key: {key}, Default: {default}, Extra: {extra}) */\n")

            # 기본 키 설정
            if IS_ENTITY_CLASS and key == "PRI":
                f.write("    @Id\n")

            if IS_ENTITY_CLASS:
                column_definition = f"{col_type}"
                if default and default != "None" and default != "NULL":
                    column_definition = f"{column_definition} DEFAULT {default}"
                if extra:
                    column_definition = f"{column_definition} {extra}"
                f.write(f"    @Column(name = \"{col_name}\", nullable = {'true' if nullable == 'YES' else 'false'}, columnDefinition = \"{column_definition}\")\n")
            f.write(f"    private {field_type} {field_name};\n\n")

        f.write("}\n")
    print(f"Generated: {file_path}")

    # 복합 키 클래스 생성
    if has_composite_key:
        composite_key_path = os.path.join(folder_path, f"{class_name}PK.java")
        with open(composite_key_path, "w", encoding="utf-8") as f:
            f.write(f"package {package_name};\n\n")
            f.write("import lombok.*;\n")
            f.write("import java.io.Serializable;\n")
            f.write("import javax.persistence.*;\n\n")
            f.write("@Data\n")
            f.write("@NoArgsConstructor\n")
            f.write("@AllArgsConstructor\n")
            f.write(f"public class {class_name}PK implements Serializable {{\n\n")
            for pk in primary_keys:
                f.write(f"    private String {to_camel_case(pk)};\n")
            f.write("}\n")
        print(f"Generated: {composite_key_path}")

print("Entity class generation completed.")
