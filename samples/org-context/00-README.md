# Northwind Therapeutics - sample org-context pack

**Northwind Therapeutics is a fictional company.** Every name, site, supplier and contract in this folder is invented. The figures are built to line up with the `pharma-sample` P&L already in the app ($480M revenue, G&A at 20.0% of revenue against a peer median of 14.2%), so the documents explain *why* that benchmark gap exists instead of contradicting it.

Upload these through **Context** in the app header to give the diagnostic operational facts a P&L cannot show.

| File | Format | What it carries |
|---|---|---|
| 01-organisation-and-headcount | PDF | G&A headcount by function and entity; works-council and retention constraints |
| 02-facilities-and-leases | PDF | Five sites, lease expiries, break clauses, 41% office occupancy |
| 03-vendor-contract-register | PDF | Top 12 suppliers, notice periods, four never tendered |
| 04-it-systems-landscape | PDF | Three ERP instances, duplicate Veeva tenancies, deferred consolidation |
| 05-commercial-operations | PDF | Three brands, 140 reps, 68% prescriber overlap |
| 06-ga-headcount-roster | XLSX | Per-function roster with duplicate flags |
| 07-integration-status-memo | DOCX | Integration state and open decisions per acquisition |
| 08-fy2025-operating-review | PPTX | Operating review deck with a constraints table |

The formats are deliberately mixed - one per extractor branch in `backend/core/rag.py`.
