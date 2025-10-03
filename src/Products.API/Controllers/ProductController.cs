using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;

namespace Products.API.Controllers
{
    [Route("api/[controller]")]
    [ApiController]
    public class ProductController : ControllerBase
    {
        // Classe de modelo simples
        public class Product
        {
            public int Id { get; set; }
            public string Name { get; set; } = string.Empty;
            public decimal Price { get; set; }
        }

        // Mock: lista estática de produtos
        private static List<Product> _products = new List<Product>
        {
            new Product { Id = 1, Name = "Teclado", Price = 150 },
            new Product { Id = 2, Name = "Mouse", Price = 80 },
            new Product { Id = 3, Name = "Monitor", Price = 1200 }
        };

        // GET: api/product
        [HttpGet]
        public ActionResult<IEnumerable<Product>> GetAll()
        {
            return Ok(_products);
        }

        // GET: api/product/2
        [HttpGet("{id}")]
        public ActionResult<Product> GetById(int id)
        {
            var product = _products.FirstOrDefault(p => p.Id == id);
            if (product == null)
                return NotFound();

            return Ok(product);
        }

        // POST: api/product
        [HttpPost]
        public async Task<ActionResult<Product>> Create(Product product)
        {
            product.Id = _products.Max(p => p.Id) + 1; // gera ID simples
            _products.Add(product);

            return CreatedAtAction(nameof(GetById), new { id = product.Id }, product);
        }

        // PUT: api/product/2
        [HttpPut("{id}")]
        public async Task<IActionResult> Update(int id, Product updatedProduct)
        {
            var product = _products.FirstOrDefault(p => p.Id == id);
            if (product == null)
                return NotFound();

            product.Name = updatedProduct.Name;
            product.Price = updatedProduct.Price;

            return NoContent();
        }

        // DELETE: api/product/2
        [HttpDelete("{id}")]
        public IActionResult Delete(int id)
        {
            var product = _products.FirstOrDefault(p => p.Id == id);
            if (product == null)
                return NotFound();

            _products.Remove(product);
            return NoContent();
        }

        [HttpGet("{id}")]
        public IActionResult Get(int id)
        {
            // Consulta “fake” + regra de negócio + formatação tudo junto
            var p = _cache.FirstOrDefault(x => x.Id == id);
            if (p == null)
            {
                // Mensagem vaga
return StatusCode(500, "Internal Server Error");
            }
            // Retorna entidade crua sem DTO
            return Ok(p);
        }
    }
}
