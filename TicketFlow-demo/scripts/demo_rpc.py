"""Demo B fallback: SOAP/WSDL a gRPC deadline (gRPC volanie robí API kontajner → grpc:50051).
Použitie:
  python3 scripts/demo_rpc.py --show-wsdl --check-seat A7
  python3 scripts/demo_rpc.py --grpc-delay-ms 800 --deadline-ms 200"""
import argparse
import re

from _client import get, line, title

p = argparse.ArgumentParser()
p.add_argument("--show-wsdl", action="store_true")
p.add_argument("--check-seat", metavar="SEAT")
p.add_argument("--soap-fault", action="store_true", help="pošli neplatný SOAP request")
p.add_argument("--grpc-delay-ms", type=int)
p.add_argument("--deadline-ms", type=int)
a = p.parse_args()

if a.show_wsdl:
    title("SOAP: GET /soap?wsdl (výrez)")
    w = get("/soap?wsdl").body
    for ln in w.splitlines():
        if "CheckSeat" in ln or "soap:address" in ln:
            print("  " + ln.strip())
if a.check_seat:
    title(f"SOAP: CheckSeat(42, {a.check_seat})")
    j = get(f"/demo/rpc/soap?seat={a.check_seat}").json
    print(j["request_xml"])
    print(f"  HTTP {j['http_status']} · request {j['request_body_bytes']} B · response {j['response_body_bytes']} B (HTTP body)")
    print(j["response_xml"])
    title(f"gRPC: CheckSeat(42, {a.check_seat})")
    g = get(f"/demo/rpc/grpc?seat={a.check_seat}").json
    print(f"  {g['code']} · reply={g.get('reply')} · {g['client_elapsed_ms']} ms")
    print(f"  protobuf: request {g['request_protobuf_bytes']} B · response {g.get('response_protobuf_bytes')} B "
          "(bez HTTP/2 rámcov a hlavičiek)")
if a.soap_fault:
    title("SOAP: neplatný request (chýba seatId)")
    j = get("/demo/rpc/soap?invalid=true").json
    print(f"  HTTP {j['http_status']} · fault={j['is_fault']}")
    print("  " + (re.search(r"<faultstring>(.*?)</faultstring>", j["response_xml"]) or [None, "?"])[1])
if a.grpc_delay_ms is not None:
    dl = f"&deadline_ms={a.deadline_ms}" if a.deadline_ms else ""
    title(f"gRPC: server delay {a.grpc_delay_ms} ms, deadline {a.deadline_ms or '—'} ms")
    g = get(f"/demo/rpc/grpc?seat=A7&delay_ms={a.grpc_delay_ms}{dl}").json
    print(f"  stav: {g['code']} · {g.get('details') or g.get('reply')}")
    print(f"  klient skončil po {g['client_elapsed_ms']} ms (deadline {a.deadline_ms} ms, server chcel pracovať {a.grpc_delay_ms} ms)")
    if a.deadline_ms and a.grpc_delay_ms > a.deadline_ms:
        line(g["code"] == "DEADLINE_EXCEEDED", "DEADLINE_EXCEEDED — čas a timeout sú odlišné pojmy")
if not any([a.show_wsdl, a.check_seat, a.soap_fault, a.grpc_delay_ms is not None]):
    p.print_help()
