"""
Google Sheets exporter with 6 tabs and batch writing.
Creates publicly viewable sheet with row counts and timestamp.
Always writes CSV fallback files.
"""
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import gspread
from google.oauth2.service_account import Credentials
from loguru import logger

from src.config import get_config, get_env_settings


class SheetsExporter:
    """
    Export pipeline data to Google Sheets.
    Creates 6 tabs: Startups, Products, Research Papers, Jobs, News, Entity Mapping Log.
    """
    
    def __init__(self, storage):
        self.storage = storage
        self.config = get_config()
        self.env_settings = get_env_settings()
        self.client: Optional[gspread.Client] = None
        self.spreadsheet: Optional[gspread.Spreadsheet] = None
    
    def _initialize_client(self) -> None:
        """Initialize Google Sheets client."""
        if self.client:
            return
        
        service_account_path = self.env_settings.google_service_account_json
        
        if not service_account_path or not Path(service_account_path).exists():
            raise ValueError(
                f"Google service account JSON not found: {service_account_path}. "
                "Set GOOGLE_SERVICE_ACCOUNT_JSON in .env"
            )
        
        try:
            # Define scopes
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive',
            ]
            
            # Load credentials
            creds = Credentials.from_service_account_file(
                service_account_path,
                scopes=scopes
            )
            
            # Create client
            self.client = gspread.authorize(creds)
            logger.info("Google Sheets client initialized")
        
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets client: {e}")
            raise
    
    async def export_all(self) -> Dict[str, Any]:
        """
        Export all data to Google Sheets and CSV.
        
        Returns:
            Dictionary with export results (URLs, row counts, etc.)
        """
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sheets_url": None,
            "csv_files": {},
            "row_counts": {},
            "errors": [],
        }
        
        # Get all data from storage
        logger.info("Fetching data from storage...")
        
        startups = await self.storage.get_all_records("STARTUP")
        products = await self.storage.get_all_records("PRODUCT")
        papers = await self.storage.get_all_records("RESEARCH_PAPER")
        jobs = await self.storage.get_all_records("JOB")
        news = await self.storage.get_all_records("NEWS")
        entity_mappings = await self.storage.get_entity_mappings()
        
        results["row_counts"] = {
            "startups": len(startups),
            "products": len(products),
            "papers": len(papers),
            "jobs": len(jobs),
            "news": len(news),
            "entity_mappings": len(entity_mappings),
        }
        
        logger.info(f"Fetched data: {results['row_counts']}")
        
        # Export to CSV (always)
        csv_dir = Path(self.config.export.csv_output_dir)
        csv_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("Exporting to CSV...")
        results["csv_files"] = {
            "startups": await self._export_csv(startups, csv_dir / "startups.csv", "STARTUP"),
            "products": await self._export_csv(products, csv_dir / "products.csv", "PRODUCT"),
            "papers": await self._export_csv(papers, csv_dir / "research_papers.csv", "RESEARCH_PAPER"),
            "jobs": await self._export_csv(jobs, csv_dir / "jobs.csv", "JOB"),
            "news": await self._export_csv(news, csv_dir / "news.csv", "NEWS"),
            "entity_mappings": await self._export_entity_mappings_csv(entity_mappings, csv_dir / "entity_mappings.csv"),
        }
        
        # Export to Google Sheets if enabled
        if "google_sheets" in self.config.export.formats:
            try:
                logger.info("Exporting to Google Sheets...")
                self._initialize_client()
                
                # Create or open spreadsheet
                sheet_title = f"GraphOne Pipeline - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                self.spreadsheet = await self._create_spreadsheet(sheet_title)
                
                # Export each tab
                await self._export_sheet_tab("Startups", startups, "STARTUP")
                await self._export_sheet_tab("Products", products, "PRODUCT")
                await self._export_sheet_tab("Research Papers", papers, "RESEARCH_PAPER")
                await self._export_sheet_tab("Jobs", jobs, "JOB")
                await self._export_sheet_tab("News", news, "NEWS")
                await self._export_entity_mappings_sheet(entity_mappings)
                
                # Add summary tab
                await self._create_summary_tab(results["row_counts"], results["timestamp"])
                
                # Make public if configured
                if self.config.export.google_sheets.make_public:
                    self.spreadsheet.share('', perm_type='anyone', role='reader')
                    logger.info("Spreadsheet made publicly readable")
                
                results["sheets_url"] = self.spreadsheet.url
                logger.info(f"Google Sheets export complete: {results['sheets_url']}")
            
            except Exception as e:
                logger.error(f"Failed to export to Google Sheets: {e}")
                results["errors"].append(f"Google Sheets export failed: {e}")
        
        return results
    
    async def _create_spreadsheet(self, title: str) -> gspread.Spreadsheet:
        """Create a new spreadsheet or use existing one."""
        if self.config.export.google_sheets.create_new:
            # Create new spreadsheet
            spreadsheet = self.client.create(title)
            logger.info(f"Created new spreadsheet: {title}")
        else:
            # Use existing spreadsheet ID if provided
            sheet_id = self.env_settings.google_sheet_id
            if not sheet_id:
                raise ValueError("GOOGLE_SHEET_ID not set in .env")
            
            spreadsheet = self.client.open_by_key(sheet_id)
            logger.info(f"Opened existing spreadsheet: {sheet_id}")
        
        return spreadsheet
    
    async def _export_sheet_tab(
        self,
        tab_name: str,
        records: List[Dict[str, Any]],
        record_type: str,
    ) -> None:
        """
        Export records to a Google Sheets tab.
        
        Args:
            tab_name: Name of the tab
            records: List of record dictionaries
            record_type: Type of records
        """
        if not records:
            logger.warning(f"No records to export for {tab_name}")
            return
        
        # Get or create worksheet
        try:
            worksheet = self.spreadsheet.worksheet(tab_name)
            worksheet.clear()
        except gspread.WorksheetNotFound:
            worksheet = self.spreadsheet.add_worksheet(
                title=tab_name,
                rows=len(records) + 100,
                cols=20,
            )
        
        # Convert records to rows
        headers, rows = self._records_to_rows(records, record_type)
        
        # Batch write
        batch_size = self.config.export.google_sheets.batch_size
        
        # Write headers
        worksheet.update('A1', [headers])
        
        # Write data in batches
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            start_row = i + 2  # +2 because 1 is headers and we're 0-indexed
            
            cell_range = f'A{start_row}'
            worksheet.update(cell_range, batch)
            
            logger.debug(f"Wrote batch to {tab_name}: rows {start_row}-{start_row + len(batch) - 1}")
        
        logger.info(f"Exported {len(rows)} rows to {tab_name}")
    
    async def _export_entity_mappings_sheet(
        self,
        mappings: List[Any],
    ) -> None:
        """Export entity mappings to Google Sheets."""
        if not mappings:
            logger.warning("No entity mappings to export")
            return
        
        tab_name = "Entity Mapping Log"
        
        try:
            worksheet = self.spreadsheet.worksheet(tab_name)
            worksheet.clear()
        except gspread.WorksheetNotFound:
            worksheet = self.spreadsheet.add_worksheet(
                title=tab_name,
                rows=len(mappings) + 100,
                cols=10,
            )
        
        # Headers
        headers = ['Raw Name', 'Canonical Name', 'Match Method', 'Score', 'Source URL', 'Timestamp']
        
        # Convert mappings to rows
        rows = []
        for mapping in mappings:
            rows.append([
                mapping.raw_name,
                mapping.canonical_name,
                mapping.match_method,
                mapping.score if mapping.score else "",
                mapping.source_url,
                mapping.timestamp.isoformat() if mapping.timestamp else "",
            ])
        
        # Write
        worksheet.update('A1', [headers])
        
        batch_size = self.config.export.google_sheets.batch_size
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            start_row = i + 2
            worksheet.update(f'A{start_row}', batch)
        
        logger.info(f"Exported {len(rows)} entity mappings")
    
    async def _create_summary_tab(
        self,
        row_counts: Dict[str, int],
        timestamp: str,
    ) -> None:
        """Create summary tab with statistics."""
        tab_name = "Summary"
        
        try:
            worksheet = self.spreadsheet.worksheet(tab_name)
            worksheet.clear()
        except gspread.WorksheetNotFound:
            worksheet = self.spreadsheet.add_worksheet(
                title=tab_name,
                rows=20,
                cols=5,
            )
        
        # Build summary data
        summary = [
            ["GraphOne Pipeline Export Summary"],
            [""],
            ["Export Timestamp", timestamp],
            [""],
            ["Record Counts"],
            ["Startups", row_counts.get("startups", 0)],
            ["Products", row_counts.get("products", 0)],
            ["Research Papers", row_counts.get("papers", 0)],
            ["Jobs", row_counts.get("jobs", 0)],
            ["News Articles", row_counts.get("news", 0)],
            ["Entity Mappings", row_counts.get("entity_mappings", 0)],
            [""],
            ["Total Records", sum(v for k, v in row_counts.items() if k != "entity_mappings")],
        ]
        
        worksheet.update('A1', summary)
        
        # Format header
        worksheet.format('A1', {
            'textFormat': {'bold': True, 'fontSize': 14},
        })
        
        logger.info("Created summary tab")
    
    def _records_to_rows(
        self,
        records: List[Dict[str, Any]],
        record_type: str,
    ) -> tuple[List[str], List[List[Any]]]:
        """
        Convert records to spreadsheet rows.
        
        Args:
            records: List of record dictionaries
            record_type: Type of records
            
        Returns:
            Tuple of (headers, rows)
        """
        if not records:
            return ([], [])
        
        # Define field mappings for each record type
        field_maps = {
            "STARTUP": [
                ("Entity Name", lambda r: r.get("content", {}).get("data", {}).get("entityName", "")),
                ("Employee Count", lambda r: r.get("content", {}).get("data", {}).get("employeeCount", "")),
                ("Source", lambda r: r.get("source", {}).get("name", "")),
                ("URL", lambda r: r.get("source", {}).get("url", "")),
                ("Collected At", lambda r: r.get("collectedAt", "")),
            ],
            "PRODUCT": [
                ("Product Name", lambda r: r.get("content", {}).get("data", {}).get("productName", "")),
                ("Startup Name", lambda r: r.get("content", {}).get("data", {}).get("startupName", "")),
                ("Pricing Model", lambda r: r.get("content", {}).get("data", {}).get("pricingModel", "")),
                ("Source", lambda r: r.get("source", {}).get("name", "")),
                ("URL", lambda r: r.get("source", {}).get("url", "")),
                ("Collected At", lambda r: r.get("collectedAt", "")),
            ],
            "RESEARCH_PAPER": [
                ("Title", lambda r: r.get("content", {}).get("data", {}).get("title", "")),
                ("Authors", lambda r: ", ".join(r.get("content", {}).get("data", {}).get("authors", []))),
                ("Paper URL", lambda r: r.get("content", {}).get("data", {}).get("paper_url", "")),
                ("GitHub URL", lambda r: r.get("content", {}).get("data", {}).get("github_url", "")),
                ("GitHub Stars", lambda r: r.get("content", {}).get("data", {}).get("github_stars", "")),
                ("Published Date", lambda r: r.get("content", {}).get("data", {}).get("published_date", "")),
                ("Source", lambda r: r.get("source", {}).get("name", "")),
                ("Collected At", lambda r: r.get("collectedAt", "")),
            ],
            "JOB": [
                ("Title", lambda r: r.get("content", {}).get("data", {}).get("title", "")),
                ("Company", lambda r: r.get("content", {}).get("data", {}).get("company", "")),
                ("Location", lambda r: r.get("content", {}).get("data", {}).get("location", "")),
                ("Is Remote", lambda r: r.get("content", {}).get("data", {}).get("is_remote", "")),
                ("Role Family", lambda r: r.get("content", {}).get("data", {}).get("role_family", "")),
                ("Date", lambda r: r.get("content", {}).get("data", {}).get("date", "")),
                ("Source", lambda r: r.get("source", {}).get("name", "")),
                ("URL", lambda r: r.get("source", {}).get("url", "")),
                ("Collected At", lambda r: r.get("collectedAt", "")),
            ],
            "NEWS": [
                ("Title", lambda r: r.get("content", {}).get("data", {}).get("title", "")),
                ("Source Name", lambda r: r.get("content", {}).get("data", {}).get("source_name", "")),
                ("Published At", lambda r: r.get("content", {}).get("data", {}).get("published_at", "")),
                ("Date Source", lambda r: r.get("content", {}).get("data", {}).get("date_source", "")),
                ("Date Confidence", lambda r: r.get("content", {}).get("data", {}).get("date_confidence", "")),
                ("URL", lambda r: r.get("content", {}).get("data", {}).get("url", "")),
                ("Summary", lambda r: (r.get("content", {}).get("data", {}).get("summary", "") or "")[:500]),
                ("Collected At", lambda r: r.get("collectedAt", "")),
            ],
        }
        
        field_map = field_maps.get(record_type, [])
        if not field_map:
            logger.warning(f"Unknown record type: {record_type}")
            return ([], [])
        
        headers = [field[0] for field in field_map]
        rows = []
        
        for record in records:
            row = []
            for _, extractor in field_map:
                try:
                    value = extractor(record)
                    # Convert to string, handle None
                    row.append(str(value) if value is not None and value != "" else "")
                except Exception as e:
                    logger.debug(f"Error extracting field: {e}")
                    row.append("")
            rows.append(row)
        
        return (headers, rows)
    
    async def _export_csv(
        self,
        records: List[Dict[str, Any]],
        file_path: Path,
        record_type: str,
    ) -> str:
        """Export records to CSV file."""
        if not records:
            logger.warning(f"No records to export to {file_path}")
            return str(file_path)
        
        headers, rows = self._records_to_rows(records, record_type)
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        
        logger.info(f"Exported {len(rows)} rows to {file_path}")
        return str(file_path)
    
    async def _export_entity_mappings_csv(
        self,
        mappings: List[Any],
        file_path: Path,
    ) -> str:
        """Export entity mappings to CSV file."""
        if not mappings:
            logger.warning(f"No entity mappings to export to {file_path}")
            return str(file_path)
        
        headers = ['Raw Name', 'Canonical Name', 'Match Method', 'Score', 'Source URL', 'Timestamp']
        rows = []
        
        for mapping in mappings:
            rows.append([
                mapping.raw_name,
                mapping.canonical_name,
                mapping.match_method,
                mapping.score if mapping.score else "",
                mapping.source_url,
                mapping.timestamp.isoformat() if mapping.timestamp else "",
            ])
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        
        logger.info(f"Exported {len(rows)} entity mappings to {file_path}")
        return str(file_path)
