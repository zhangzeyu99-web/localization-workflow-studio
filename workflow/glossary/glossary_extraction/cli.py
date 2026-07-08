"""Argparse construction and CLI orchestration for glossary extraction."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from glossary_extraction.ai_supplement import (
    AiSupplementProvider,
    PacketOnlyAiSupplementProvider,
    build_ai_evidence_candidate_rows_from_workbook,
    build_multilingual_ai_candidate_rows,
    configure_utf8_stdio,
    resolve_ai_supplement_provider,
    run_ai_supplement_flow,
)
from glossary_extraction.announcement import (
    build_announcement_candidate_rows,
    build_announcement_candidate_rows_from_workbook,
    build_multilingual_announcement_rows,
    load_announcement_texts,
    parse_language_table_specs,
    select_announcement_term_rows,
    write_announcement_glossary_workbook,
    write_announcement_validation_report,
)
from glossary_extraction.constants import (
    DEFAULT_AI_SUPPLEMENT_MODEL,
    DEFAULT_CURATED_RULES,
    DEFAULT_OBSERVATIONS_STORE,
    DEFAULT_OPENAI_RESPONSES_API_URL,
)
from glossary_extraction.excel_io import (
    display_header_name,
    file_digest,
    load_project_material_records,
    load_project_records,
    load_records,
    write_detail_workbook,
    write_final_workbook,
    write_text_output,
)
from glossary_extraction.experience import (
    load_curated_rules,
    load_observation_store,
    save_curated_rules,
    save_observation_store,
)
from glossary_extraction.heuristics import build_term_rows, clean_text
from glossary_extraction.models import Record
from glossary_extraction.reporting import build_project_brief


def default_output_paths(input_path: Path, detail_output: str | None, final_output: str | None) -> tuple[Path, Path]:
    date_suffix = datetime.now().strftime("%Y%m%d")
    detail_path = Path(detail_output) if detail_output else input_path.with_name(
        f"{input_path.stem}_glossary_details_{date_suffix}.xlsx"
    )
    final_path = Path(final_output) if final_output else input_path.with_name(
        f"{input_path.stem}_ID_CN_EN_EN2_{date_suffix}.xlsx"
    )
    return detail_path, final_path


def default_project_brief_output_path(input_path: Path, project_brief_output: str | None) -> Path:
    date_suffix = datetime.now().strftime("%Y%m%d")
    return Path(project_brief_output) if project_brief_output else input_path.with_name(
        f"{input_path.stem}_project_brief_{date_suffix}.md"
    )


def default_announcement_output_path(material_paths: list[Path], announcement_output: str | None) -> Path | None:
    if announcement_output:
        return Path(announcement_output)
    if not material_paths:
        return None
    date_suffix = datetime.now().strftime("%Y%m%d")
    first_material = material_paths[0]
    return first_material.with_name(f"{first_material.stem}_announcement_terms_{date_suffix}.xlsx")


def default_announcement_validation_output_path(
    material_paths: list[Path],
    announcement_validation_output: str | None,
) -> Path | None:
    if announcement_validation_output:
        return Path(announcement_validation_output)
    return None


def default_ai_supplement_packet_output_path(
    material_paths: list[Path],
    ai_supplement_packet_output: str | None,
) -> Path | None:
    if ai_supplement_packet_output:
        return Path(ai_supplement_packet_output)
    if not material_paths:
        return None
    date_suffix = datetime.now().strftime("%Y%m%d")
    first_material = material_paths[0]
    return first_material.with_name(f"{first_material.stem}_ai_packet_{date_suffix}.json")


def default_ai_supplement_report_output_path(
    material_paths: list[Path],
    ai_supplement_report_output: str | None,
) -> Path | None:
    if ai_supplement_report_output:
        return Path(ai_supplement_report_output)
    if not material_paths:
        return None
    date_suffix = datetime.now().strftime("%Y%m%d")
    first_material = material_paths[0]
    return first_material.with_name(f"{first_material.stem}_ai_supplement_{date_suffix}.md")


def should_run_announcement_only(args: argparse.Namespace) -> bool:
    return bool(args.announcement_material) and not any(
        [
            args.output,
            args.final_output,
            args.project_brief_output,
            args.translation_prompt_output,
            args.project_material,
            args.project_note,
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract glossary terms from a game localization language table.")
    parser.add_argument("input_path", nargs="?", help="Path to the source XLSX language table.")
    parser.add_argument("--sheet", help="Worksheet name. Defaults to the first sheet.")
    parser.add_argument("--id-column", default="ID", help="ID column header. Default: ID")
    parser.add_argument("--source-column", default="cn", help="Source text column header. Default: cn")
    parser.add_argument("--target-column", default="en", help="Target text column header. Default: en")
    parser.add_argument(
        "--language-table",
        action="append",
        default=[],
        help="Announcement lookup language table in LANG=path form. Can be repeated, for example EN=table.xlsx.",
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Treat the input as source text only and do not require a target text column.",
    )
    parser.add_argument(
        "--include-empty-final-terms",
        action="store_true",
        help="Keep final glossary rows even when EN and EN2 are blank. Useful for source-only extraction.",
    )
    parser.add_argument("--min-hit", type=int, default=5, help="Minimum hit count to keep a candidate. Default: 5")
    parser.add_argument(
        "--glossary-hit-threshold",
        type=int,
        default=10,
        help="Minimum hit count to include a candidate in the delivery glossary unless it is high risk. Default: 10",
    )
    parser.add_argument("--output", help="Path for the detailed workbook output.")
    parser.add_argument("--final-output", help="Path for the clean delivery workbook output.")
    parser.add_argument(
        "--curated-rules",
        default=str(DEFAULT_CURATED_RULES),
        help="Path to the curated glossary rules JSON file. Default: data/experience/curated_terms.json",
    )
    parser.add_argument(
        "--observations-store",
        default=str(DEFAULT_OBSERVATIONS_STORE),
        help="Path to the observed term usage JSON file. Default: data/experience/observed_terms.json",
    )
    parser.add_argument(
        "--project-name",
        help="Project name used in the project brief. Defaults to the input file stem.",
    )
    parser.add_argument(
        "--project-brief-output",
        help="Path for the project audit Markdown output. Defaults to *_project_brief_YYYYMMDD.md.",
    )
    parser.add_argument(
        "--translation-prompt-output",
        help="Optional path for a prompt-only text output extracted from the project brief.",
    )
    parser.add_argument(
        "--project-material",
        action="append",
        default=[],
        help="Additional project material path for brief generation. Can be repeated. Supports txt/md/json/csv/tsv/xlsx and image filenames.",
    )
    parser.add_argument(
        "--project-note",
        action="append",
        default=[],
        help="Additional project note or image observation used for brief generation. Can be repeated.",
    )
    parser.add_argument(
        "--no-project-brief",
        action="store_true",
        help="Disable project audit Markdown generation.",
    )
    parser.add_argument(
        "--announcement-material",
        action="append",
        default=[],
        help="Version announcement material path. Can be repeated. Supports docx/txt/md/json/csv/tsv/xlsx.",
    )
    parser.add_argument(
        "--announcement-output",
        help="Path for the announcement-specific glossary workbook output.",
    )
    parser.add_argument(
        "--announcement-validation-output",
        help="Path for the announcement validation Markdown report.",
    )
    parser.add_argument(
        "--announcement-min-hit",
        type=int,
        default=1,
        help="Minimum hit count used when matching language-table terms against announcement text. Default: 1",
    )
    parser.add_argument(
        "--ai-supplement",
        action="store_true",
        help="Enable optional AI supplement flow for announcement glossary lookup. In auto mode, uses response file first, then OPENAI_API_KEY, then packet-only fallback.",
    )
    parser.add_argument(
        "--ai-supplement-provider",
        choices=["auto", "packet", "file", "openai"],
        default="auto",
        help="AI supplement provider. auto uses --ai-supplement-response if present, otherwise OpenAI when OPENAI_API_KEY is set, otherwise packet-only. Default: auto",
    )
    parser.add_argument(
        "--ai-supplement-packet-output",
        help="Path for the compact AI supplement JSON packet. Defaults to *_ai_packet_YYYYMMDD.json.",
    )
    parser.add_argument(
        "--ai-supplement-response",
        help="Path to a structured AI supplement response JSON file to merge into the announcement workbook.",
    )
    parser.add_argument(
        "--ai-supplement-report-output",
        help="Path for the AI supplement sidecar report. Defaults to *_ai_supplement_YYYYMMDD.md.",
    )
    parser.add_argument(
        "--ai-supplement-model",
        default=os.environ.get("OPENAI_MODEL", DEFAULT_AI_SUPPLEMENT_MODEL),
        help=f"OpenAI model used when the AI supplement provider is openai. Default: OPENAI_MODEL or {DEFAULT_AI_SUPPLEMENT_MODEL}",
    )
    parser.add_argument(
        "--ai-supplement-api-url",
        default=os.environ.get("OPENAI_RESPONSES_API_URL", DEFAULT_OPENAI_RESPONSES_API_URL),
        help="OpenAI Responses API URL used by the openai provider.",
    )
    parser.add_argument(
        "--ai-supplement-timeout",
        type=int,
        default=60,
        help="Timeout in seconds for automatic AI supplement provider calls. Default: 60",
    )
    return parser


def run_announcement_glossary_outputs(
    *,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    announcement_rows: list[dict[str, object]],
    announcement_text: str,
    headers: list[str],
    project_name: str,
    build_ai_candidate_rows: Callable[[], list[dict[str, object]]],
    announcement_output_path: Path,
    announcement_validation_output_path: Path | None,
    announcement_material_paths: list[Path],
    language_tables: list[str],
    validation_stats: dict[str, int],
    ai_supplement_packet_output_path: Path | None,
    ai_supplement_report_output_path: Path | None,
    ai_supplement_response_path: Path | None,
    ai_supplement_provider: AiSupplementProvider | None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    # Shared by the multilingual, announcement-only, and full-extraction CLI
    # branches: optional AI supplement, glossary workbook, validation report.
    ai_supplement_report: dict[str, object] | None = None
    if args.ai_supplement:
        if ai_supplement_packet_output_path is None or ai_supplement_report_output_path is None:
            parser.error("--ai-supplement output paths could not be resolved.")
        announcement_rows, ai_supplement_report, _packet_path, _report_path = run_ai_supplement_flow(
            announcement_rows=announcement_rows,
            announcement_candidate_rows=build_ai_candidate_rows(),
            announcement_text=announcement_text,
            headers=headers,
            project_name=project_name,
            packet_output_path=ai_supplement_packet_output_path,
            report_output_path=ai_supplement_report_output_path,
            response_path=ai_supplement_response_path,
            provider=ai_supplement_provider or PacketOnlyAiSupplementProvider(),
        )
    write_announcement_glossary_workbook(
        output_path=announcement_output_path,
        matched_rows=announcement_rows,
        id_header=args.id_column,
        source_header=args.source_column,
        target_header=args.target_column,
        headers=headers,
    )
    if announcement_validation_output_path is not None:
        write_announcement_validation_report(
            output_path=announcement_validation_output_path,
            announcement_materials=announcement_material_paths,
            language_tables=language_tables,
            glossary_output_path=announcement_output_path,
            rows=announcement_rows,
            headers=headers,
            stats=validation_stats,
        )
    return announcement_rows, ai_supplement_report


def run_single_table_announcement_flow(
    *,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    input_path: Path,
    records: list[Record],
    curated_rules: dict[str, Any],
    project_name: str,
    announcement_material_paths: list[Path],
    announcement_output_path: Path,
    announcement_validation_output_path: Path | None,
    ai_supplement_packet_output_path: Path | None,
    ai_supplement_report_output_path: Path | None,
    ai_supplement_response_path: Path | None,
    ai_supplement_provider: AiSupplementProvider | None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    # Shared single-workbook announcement lookup used by the announcement-only
    # branch and the full extraction + announcement branch.
    announcement_headers, announcement_candidate_rows = build_announcement_candidate_rows_from_workbook(
        input_path=input_path,
        sheet_name=args.sheet,
        id_column=args.id_column,
        source_column=args.source_column,
        target_column=args.target_column,
        min_hit=args.announcement_min_hit,
        curated_rules=curated_rules,
        source_only=args.source_only,
    )
    if not announcement_candidate_rows:
        announcement_records = load_project_records(input_path) or records
        announcement_candidate_rows = build_announcement_candidate_rows(
            records=announcement_records,
            min_hit=args.announcement_min_hit,
            curated_rules=curated_rules,
        )
    announcement_text = load_announcement_texts(announcement_material_paths)
    announcement_rows = select_announcement_term_rows(
        term_rows=announcement_candidate_rows,
        announcement_text=announcement_text,
        include_empty=args.include_empty_final_terms,
    )
    output_headers = announcement_headers or [
        display_header_name(args.id_column, "ID"),
        display_header_name(args.source_column, "CN"),
        display_header_name(args.target_column, "EN"),
    ]

    def build_ai_candidate_rows() -> list[dict[str, object]]:
        return build_ai_evidence_candidate_rows_from_workbook(
            input_path=input_path,
            sheet_name=args.sheet,
            id_column=args.id_column,
            source_column=args.source_column,
            target_column=args.target_column,
            language=display_header_name(args.target_column, "EN"),
            source_only=args.source_only,
        ) or announcement_candidate_rows

    return run_announcement_glossary_outputs(
        parser=parser,
        args=args,
        announcement_rows=announcement_rows,
        announcement_text=announcement_text,
        headers=output_headers,
        project_name=project_name,
        build_ai_candidate_rows=build_ai_candidate_rows,
        announcement_output_path=announcement_output_path,
        announcement_validation_output_path=announcement_validation_output_path,
        announcement_material_paths=announcement_material_paths,
        language_tables=[f"{display_header_name(args.target_column, 'EN')}: {input_path}"],
        validation_stats={"candidate_terms": len(announcement_candidate_rows)},
        ai_supplement_packet_output_path=ai_supplement_packet_output_path,
        ai_supplement_report_output_path=ai_supplement_report_output_path,
        ai_supplement_response_path=ai_supplement_response_path,
        ai_supplement_provider=ai_supplement_provider,
    )


def print_ai_supplement_summary(
    *,
    args: argparse.Namespace,
    ai_supplement_packet_output_path: Path | None,
    ai_supplement_report_output_path: Path | None,
    ai_supplement_provider: AiSupplementProvider | None,
    ai_supplement_report: dict[str, object] | None,
    project_name: str | None,
) -> None:
    print(f"AI_SUPPLEMENT_PACKET_OUTPUT={ai_supplement_packet_output_path if args.ai_supplement else 'disabled'}")
    print(f"AI_SUPPLEMENT_REPORT_OUTPUT={ai_supplement_report_output_path if args.ai_supplement else 'disabled'}")
    print(f"AI_SUPPLEMENT_PROVIDER={ai_supplement_provider.name if ai_supplement_provider else 'disabled'}")
    if ai_supplement_report and ai_supplement_report.get("provider_error"):
        print(f"AI_SUPPLEMENT_PROVIDER_ERROR={ai_supplement_report.get('provider_error')}")
    if ai_supplement_report and ai_supplement_report.get("project_name_translation_missing"):
        print(f"PROJECT_NAME_TRANSLATION_MISSING={clean_text(project_name)}")


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        language_table_specs = parse_language_table_specs(args.language_table)
    except ValueError as exc:
        parser.error(str(exc))
    if args.input_path and language_table_specs:
        parser.error("Use either positional input_path or --language-table, not both.")
    if not args.input_path and not language_table_specs:
        parser.error("input_path or at least one --language-table LANG=path is required.")

    announcement_material_paths = [Path(path) for path in args.announcement_material]
    announcement_output_path = default_announcement_output_path(
        material_paths=announcement_material_paths,
        announcement_output=args.announcement_output,
    )
    announcement_validation_output_path = default_announcement_validation_output_path(
        material_paths=announcement_material_paths,
        announcement_validation_output=args.announcement_validation_output,
    )
    ai_supplement_packet_output_path = default_ai_supplement_packet_output_path(
        material_paths=announcement_material_paths,
        ai_supplement_packet_output=args.ai_supplement_packet_output,
    )
    ai_supplement_report_output_path = default_ai_supplement_report_output_path(
        material_paths=announcement_material_paths,
        ai_supplement_report_output=args.ai_supplement_report_output,
    )
    ai_supplement_response_path = Path(args.ai_supplement_response) if args.ai_supplement_response else None
    if any([args.ai_supplement_packet_output, args.ai_supplement_response, args.ai_supplement_report_output]) and not args.ai_supplement:
        parser.error("--ai-supplement is required when using AI supplement packet, response, or report options.")
    if args.ai_supplement and not announcement_material_paths:
        parser.error("--ai-supplement is only supported with --announcement-material.")
    ai_supplement_provider: AiSupplementProvider | None = None
    if args.ai_supplement:
        try:
            ai_supplement_provider = resolve_ai_supplement_provider(
                provider_name=args.ai_supplement_provider,
                response_path=ai_supplement_response_path,
                model=args.ai_supplement_model,
                api_url=args.ai_supplement_api_url,
                timeout_seconds=args.ai_supplement_timeout,
            )
        except ValueError as exc:
            parser.error(str(exc))
    curated_rules_path = Path(args.curated_rules) if args.curated_rules else None
    observations_store_path = Path(args.observations_store) if args.observations_store else None
    curated_rules = load_curated_rules(curated_rules_path)
    observations_store = load_observation_store(observations_store_path)

    if language_table_specs:
        if not announcement_material_paths:
            parser.error("--language-table is only supported with --announcement-material.")
        if any([args.output, args.final_output, args.project_brief_output, args.translation_prompt_output, args.project_material, args.project_note]):
            parser.error("--language-table cannot be combined with full glossary or project brief outputs.")
        if announcement_output_path is None:
            parser.error("--announcement-output could not be resolved.")
        announcement_text = load_announcement_texts(announcement_material_paths)
        announcement_rows, announcement_stats = build_multilingual_announcement_rows(
            language_table_specs=language_table_specs,
            sheet_name=args.sheet,
            id_column=args.id_column,
            source_column=args.source_column,
            curated_rules=curated_rules,
            announcement_min_hit=args.announcement_min_hit,
            source_only=args.source_only,
            announcement_text=announcement_text,
            include_empty=args.include_empty_final_terms,
        )
        announcement_headers = ["ID", "CN", *[spec.language for spec in language_table_specs]]
        announcement_rows, ai_supplement_report = run_announcement_glossary_outputs(
            parser=parser,
            args=args,
            announcement_rows=announcement_rows,
            announcement_text=announcement_text,
            headers=announcement_headers,
            project_name=args.project_name or "",
            build_ai_candidate_rows=lambda: build_multilingual_ai_candidate_rows(
                language_table_specs=language_table_specs,
                sheet_name=args.sheet,
                id_column=args.id_column,
                source_column=args.source_column,
                curated_rules=curated_rules,
                announcement_min_hit=args.announcement_min_hit,
                source_only=args.source_only,
            ),
            announcement_output_path=announcement_output_path,
            announcement_validation_output_path=announcement_validation_output_path,
            announcement_material_paths=announcement_material_paths,
            language_tables=[f"{spec.language}: {spec.path}" for spec in language_table_specs],
            validation_stats=announcement_stats,
            ai_supplement_packet_output_path=ai_supplement_packet_output_path,
            ai_supplement_report_output_path=ai_supplement_report_output_path,
            ai_supplement_response_path=ai_supplement_response_path,
            ai_supplement_provider=ai_supplement_provider,
        )

        print("INPUT=multi-language")
        print("DETAIL_OUTPUT=disabled")
        print("FINAL_OUTPUT=disabled")
        print("PROJECT_BRIEF_OUTPUT=disabled")
        print("TRANSLATION_PROMPT_OUTPUT=disabled")
        print(f"ANNOUNCEMENT_OUTPUT={announcement_output_path}")
        print(f"ANNOUNCEMENT_VALIDATION_OUTPUT={announcement_validation_output_path or 'disabled'}")
        print(f"ANNOUNCEMENT_MATERIALS={len(announcement_material_paths)}")
        print(f"ANNOUNCEMENT_TERMS={len(announcement_rows)}")
        print(f"LANGUAGE_TABLES={len(language_table_specs)}")
        print(f"CURATED_RULES={curated_rules_path or 'disabled'}")
        print(f"OBSERVATIONS_STORE={observations_store_path or 'disabled'}")
        print_ai_supplement_summary(
            args=args,
            ai_supplement_packet_output_path=ai_supplement_packet_output_path,
            ai_supplement_report_output_path=ai_supplement_report_output_path,
            ai_supplement_provider=ai_supplement_provider,
            ai_supplement_report=ai_supplement_report,
            project_name=args.project_name,
        )
        return 0

    input_path = Path(args.input_path)
    detail_output_path, final_output_path = default_output_paths(
        input_path=input_path,
        detail_output=args.output,
        final_output=args.final_output,
    )
    project_name = args.project_name or input_path.stem
    project_brief_output_path = default_project_brief_output_path(
        input_path=input_path,
        project_brief_output=args.project_brief_output,
    )
    translation_prompt_output_path = Path(args.translation_prompt_output) if args.translation_prompt_output else None
    announcement_only = should_run_announcement_only(args)
    digest = file_digest(input_path)

    records, sheet_name = load_records(
        input_path=input_path,
        sheet_name=args.sheet,
        id_column=args.id_column,
        source_column=args.source_column,
        target_column=args.target_column,
        source_only=args.source_only,
    )
    if announcement_only and announcement_output_path is not None:
        announcement_rows, ai_supplement_report = run_single_table_announcement_flow(
            parser=parser,
            args=args,
            input_path=input_path,
            records=records,
            curated_rules=curated_rules,
            project_name=args.project_name or "",
            announcement_material_paths=announcement_material_paths,
            announcement_output_path=announcement_output_path,
            announcement_validation_output_path=announcement_validation_output_path,
            ai_supplement_packet_output_path=ai_supplement_packet_output_path,
            ai_supplement_report_output_path=ai_supplement_report_output_path,
            ai_supplement_response_path=ai_supplement_response_path,
            ai_supplement_provider=ai_supplement_provider,
        )

        print(f"INPUT={input_path}")
        print("DETAIL_OUTPUT=disabled")
        print("FINAL_OUTPUT=disabled")
        print("PROJECT_BRIEF_OUTPUT=disabled")
        print("TRANSLATION_PROMPT_OUTPUT=disabled")
        print(f"ANNOUNCEMENT_OUTPUT={announcement_output_path}")
        print(f"ANNOUNCEMENT_VALIDATION_OUTPUT={announcement_validation_output_path or 'disabled'}")
        print(f"ANNOUNCEMENT_MATERIALS={len(announcement_material_paths)}")
        print(f"ANNOUNCEMENT_TERMS={len(announcement_rows)}")
        print(f"CURATED_RULES={curated_rules_path or 'disabled'}")
        print(f"OBSERVATIONS_STORE={observations_store_path or 'disabled'}")
        print(f"SHEET={sheet_name}")
        print(f"RECORDS={len(records)}")
        print_ai_supplement_summary(
            args=args,
            ai_supplement_packet_output_path=ai_supplement_packet_output_path,
            ai_supplement_report_output_path=ai_supplement_report_output_path,
            ai_supplement_provider=ai_supplement_provider,
            ai_supplement_report=ai_supplement_report,
            project_name=args.project_name,
        )
        return 0

    all_rows, glossary_rows, high_risk_rows, manual_rows, final_rows = build_term_rows(
        records=records,
        min_hit=args.min_hit,
        glossary_hit_threshold=args.glossary_hit_threshold,
        curated_rules=curated_rules,
        observations_store=observations_store,
        input_digest=digest,
        include_empty_final_terms=args.include_empty_final_terms,
    )

    write_detail_workbook(
        output_path=detail_output_path,
        sheet_name=sheet_name,
        records=records,
        all_rows=all_rows,
        glossary_rows=glossary_rows,
        high_risk_rows=high_risk_rows,
        manual_rows=manual_rows,
        curated_rules_path=curated_rules_path,
        observations_store_path=observations_store_path,
    )
    write_final_workbook(output_path=final_output_path, final_rows=final_rows)
    material_records, material_sources = load_project_material_records(
        material_paths=[Path(path) for path in args.project_material],
        notes=args.project_note,
    )
    project_records = records if args.no_project_brief and translation_prompt_output_path is None else (
        (load_project_records(input_path) or records) + material_records
    )
    project_brief_markdown, translation_prompt = build_project_brief(
        project_name=project_name,
        sheet_name=sheet_name,
        records=project_records,
        all_rows=all_rows,
        glossary_rows=glossary_rows,
        manual_rows=manual_rows,
        material_sources=material_sources,
    )
    if not args.no_project_brief:
        write_text_output(project_brief_output_path, project_brief_markdown)
    if translation_prompt_output_path is not None:
        write_text_output(translation_prompt_output_path, translation_prompt)

    announcement_rows: list[dict[str, object]] = []
    ai_supplement_report: dict[str, object] | None = None
    if announcement_material_paths and announcement_output_path is not None:
        announcement_rows, ai_supplement_report = run_single_table_announcement_flow(
            parser=parser,
            args=args,
            input_path=input_path,
            records=records,
            curated_rules=curated_rules,
            project_name=project_name,
            announcement_material_paths=announcement_material_paths,
            announcement_output_path=announcement_output_path,
            announcement_validation_output_path=announcement_validation_output_path,
            ai_supplement_packet_output_path=ai_supplement_packet_output_path,
            ai_supplement_report_output_path=ai_supplement_report_output_path,
            ai_supplement_response_path=ai_supplement_response_path,
            ai_supplement_provider=ai_supplement_provider,
        )

    save_curated_rules(curated_rules_path, curated_rules)
    save_observation_store(observations_store_path, observations_store)

    print(f"INPUT={input_path}")
    print(f"DETAIL_OUTPUT={detail_output_path}")
    print(f"FINAL_OUTPUT={final_output_path}")
    print(f"PROJECT_BRIEF_OUTPUT={project_brief_output_path if not args.no_project_brief else 'disabled'}")
    print(f"TRANSLATION_PROMPT_OUTPUT={translation_prompt_output_path or 'disabled'}")
    print(f"ANNOUNCEMENT_OUTPUT={announcement_output_path if announcement_output_path else 'disabled'}")
    print(f"ANNOUNCEMENT_VALIDATION_OUTPUT={announcement_validation_output_path if announcement_validation_output_path else 'disabled'}")
    print(f"ANNOUNCEMENT_MATERIALS={len(announcement_material_paths)}")
    print(f"ANNOUNCEMENT_TERMS={len(announcement_rows)}")
    print(f"PROJECT_MATERIALS={len(material_sources)}")
    print(f"CURATED_RULES={curated_rules_path or 'disabled'}")
    print(f"OBSERVATIONS_STORE={observations_store_path or 'disabled'}")
    print(f"SHEET={sheet_name}")
    print(f"RECORDS={len(records)}")
    print(f"CANDIDATES={len(all_rows)}")
    print(f"GLOSSARY_ROWS={len(glossary_rows)}")
    print(f"HIGH_RISK_ROWS={len(high_risk_rows)}")
    print(f"MANUAL_ADAPTATION_ROWS={len(manual_rows)}")
    print_ai_supplement_summary(
        args=args,
        ai_supplement_packet_output_path=ai_supplement_packet_output_path,
        ai_supplement_report_output_path=ai_supplement_report_output_path,
        ai_supplement_provider=ai_supplement_provider,
        ai_supplement_report=ai_supplement_report,
        project_name=project_name,
    )
    print(f"FINAL_ROWS={len(final_rows)}")
    return 0
