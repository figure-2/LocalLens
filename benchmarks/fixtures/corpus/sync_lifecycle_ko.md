동기화 리포트는 added, updated, deleted, skipped, excluded, failed를 분리해서 기록한다.
변경되지 않은 파일은 skipped로 남고, 사라진 파일의 검색 단위는 manifest 기준으로 제거된다.
실패한 파일은 전체 인덱싱을 중단하지 않고 failed 집계에 반영한다.
