"""Tiny local server hosting fictional company websites so the whole pipeline can be demoed offline.
Run:  python demo/serve.py   (serves http://127.0.0.1:8800/<slug>/)
Then start the app with ALLOW_PRIVATE_FETCH=1 so the researcher may fetch localhost."""
from http.server import BaseHTTPRequestHandler, HTTPServer

def page(title, desc, body, extra="", year=2025):
    return f"""<!doctype html><html><head><meta charset=utf-8><title>{title}</title>
<meta name="description" content="{desc}"></head><body>
<nav><a href="/{{slug}}/">Home</a><a href="/{{slug}}/about">About</a><a href="/{{slug}}/services">Services</a><a href="/{{slug}}/contact">Contact</a></nav>
{body}{extra}<footer>&copy; {year} {title.split('|')[0].strip()}. All rights reserved.</footer></body></html>"""

SITES = {
 "brightleaf": dict(
   home=page("Brightleaf Organics | Organic pantry staples", "Brightleaf Organics sells certified organic pantry staples, teas and snacks delivered across the United States.",
     "<h1>Organic food, delivered</h1><h2>Organic teas</h2><h2>Pantry staples</h2><h2>Snack boxes</h2><p>Shop our full collection of certified organic products. Add to cart and checkout in seconds with free delivery over $50.</p><a href='/cart'>Cart</a><button>Add to cart</button><p>Every order is packed in our warehouse and shipped within 24 hours to customers nationwide.</p><script src='https://cdn.shopify.com/s/x.js'></script>", "<a href='/blog'>Blog</a>"),
   about=page("About | Brightleaf Organics", "Family-run organic store", "<h1>Our story</h1><p>Brightleaf started in a small kitchen and grew into a nationwide online store for organic food with a loyal base of customers who love healthy living.</p>"),
   services=page("Shop | Brightleaf Organics", "Products", "<h1>Collections</h1><ul><li>Organic green tea</li><li>Gluten-free granola</li><li>Subscription boxes</li></ul><p>Our brand is built on trust, with fresh products sourced from small farms and delivered to your door.</p>")),
 "northwind": dict(
   home=page("Northwind Freight | UK road & sea freight", "Northwind Freight provides road, sea and warehousing logistics across the UK and Europe.",
     "<h1>Freight &amp; logistics you can track</h1><h2>Road freight</h2><h2>Sea freight</h2><h2>Warehousing &amp; distribution</h2><p>We move cargo across the UK and Europe with a modern fleet, secure warehouse facilities and a supply chain team that keeps your shipping on schedule.</p><p>Use our client portal to track your consignment and download delivery paperwork.</p><a href='/portal'>Client portal login</a><a href='/careers'>We are hiring</a>"),
   about=page("About | Northwind Freight", "About", "<h1>About Northwind</h1><p>Founded in Leeds, Northwind is an independent logistics company specialising in freight forwarding, customs clearance and warehousing for manufacturers and retailers.</p>"),
   services=page("Services | Northwind Freight", "Services", "<h1>What we do</h1><ul><li>Customs clearance</li><li>Temperature-controlled transport</li><li>Pallet distribution</li></ul><p>Contact us for a quote.</p><form><input type=email></form>")),
 "meridian": dict(
   home=page("Meridian Dental Care | Family dental clinic in Melbourne", "Meridian Dental Care is a family dental clinic offering check-ups, orthodontics and cosmetic dentistry for patients in Melbourne.",
     "<h1>Gentle dental care for the whole family</h1><h2>Check-ups &amp; cleaning</h2><h2>Orthodontics</h2><h2>Cosmetic dentistry</h2><p>Our dentists and care team look after patients of all ages. Book an appointment online or call the clinic. New patient forms can be filled in before your visit.</p><a href='/book'>Book an appointment</a><form><input type=email></form><p>Contact our clinic with any enquiry.</p>", year=2019),
   about=page("About | Meridian Dental Care", "About", "<h1>Our clinic</h1><p>Meridian Dental Care has served patients across Melbourne for over a decade with a focus on comfortable, modern dental treatment.</p>"),
   services=page("Treatments | Meridian Dental Care", "Treatments", "<h1>Treatments</h1><ul><li>Teeth whitening</li><li>Dental implants</li><li>Children's dentistry</li></ul>")),
 "kessler": dict(
   home=page("Kessler Maschinenbau | Precision machinery", "Kessler Maschinenbau manufactures precision machinery and industrial components for the automotive and packaging industries.",
     "<h1>Präzision aus Stuttgart</h1><h2>CNC machining</h2><h2>Industrial automation components</h2><h2>Assembly lines</h2><p>Our factory produces machinery and components for the automotive and packaging industry. Engineering teams design, manufacture and assemble every machine in-house at our plant.</p><p>We ship production equipment worldwide.</p>", year=2021),
   about=page("Über uns | Kessler Maschinenbau", "About", "<h1>Company</h1><p>Family-owned manufacturer of industrial machinery, serving engineering and production customers since 1974.</p>"),
   services=page("Products | Kessler Maschinenbau", "Products", "<h1>Products</h1><ul><li>Packaging machines</li><li>Conveyor systems</li><li>Spare parts</li></ul>")),
 "solaris": dict(
   home=page("Solaris Estates | Dubai property", "Solaris Estates helps buyers, sellers and investors find apartments, villas and commercial property in Dubai.",
     "<h1>Find your property in Dubai</h1><h2>Apartments for sale</h2><h2>Villas &amp; townhouses</h2><h2>Property management</h2><p>Browse hundreds of property listings. Our real estate agents help with leasing, valuations and investment advice. Enquire about any listing through the form.</p><form><input type=email></form><p>Contact us to book a viewing.</p><script src='https://embed.tawk.to/x'></script>"),
   about=page("About | Solaris Estates", "About", "<h1>About us</h1><p>A Dubai-based real estate agency with a team of property consultants serving international buyers.</p>"),
   services=page("Services | Solaris Estates", "Services", "<h1>Services</h1><ul><li>Property valuation</li><li>Mortgage assistance</li></ul>")),
 "lotus": dict(
   home=page("Lotus Legal Associates | Corporate law firm", "Lotus Legal Associates is a law firm advising businesses on contracts, compliance and corporate legal matters.",
     "<h1>Trusted legal advisory</h1><h2>Contract drafting &amp; review</h2><h2>Corporate compliance</h2><h2>Intellectual property</h2><p>Our attorneys advise companies on contracts, regulatory compliance and disputes. Request a consultation through our contact form.</p><form><input type=email></form><p>Contact us for an enquiry.</p>", year=2020),
   about=page("About | Lotus Legal", "About", "<h1>About the firm</h1><p>A legal advisory and consulting practice working with growing businesses.</p>"),
   services=page("Practice areas | Lotus Legal", "Practice areas", "<h1>Practice areas</h1><ul><li>Commercial contracts</li><li>Employment law</li></ul>")),
}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        if self.path == "/robots.txt":
            self.send_response(404); self.end_headers(); return
        if not parts or parts[0] not in SITES:
            self.send_response(404); self.end_headers(); self.wfile.write(b"not found"); return
        site = SITES[parts[0]]
        key = {"": "home", "about": "about", "services": "services"}.get(parts[1] if len(parts) > 1 else "", None)
        if key is None or key not in site:
            self.send_response(404); self.end_headers(); return
        html = site[key].replace("{slug}", parts[0]).encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(html)

if __name__ == "__main__":
    print("Demo sites on http://127.0.0.1:8800/<brightleaf|northwind|meridian|kessler|solaris|lotus>/")
    HTTPServer(("127.0.0.1", 8800), H).serve_forever()
