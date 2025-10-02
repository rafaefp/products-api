using System.Reflection;
using Microsoft.AspNetCore.Mvc;
using Products.API.Controllers;
using static Products.API.Controllers.ProductController;

namespace Products.UnitTest.Controllers
{
    public class ProductControllerTests
    {
        private readonly ProductController _sut = new ProductController();

        public ProductControllerTests()
        {
            // Resetar estado estático antes de cada teste para isolamento
            var productsField = typeof(ProductController).GetField("_products", BindingFlags.NonPublic | BindingFlags.Static);
            productsField!.SetValue(null, new List<Product>
            {
                new Product { Id = 1, Name = "Teclado", Price = 150 },
                new Product { Id = 2, Name = "Mouse",   Price = 80  },
                new Product { Id = 3, Name = "Monitor", Price = 1200 }
            });
        }

        [Fact]
        public void GetAll_returns_all_products()
        {
            // Act
            var actionResult = _sut.GetAll();

            // Assert
            var ok = Assert.IsType<OkObjectResult>(actionResult.Result);
            var products = Assert.IsAssignableFrom<IEnumerable<Product>>(ok.Value);
            Assert.Equal(3, products.Count());
        }

        [Fact]
        public void GetById_returns_product_when_exists()
        {
            // Act
            var actionResult = _sut.GetById(2);

            // Assert
            var ok = Assert.IsType<OkObjectResult>(actionResult.Result);
            var product = Assert.IsType<Product>(ok.Value);
            Assert.Equal(2, product.Id);
            Assert.Equal("Mouse", product.Name);
        }

        [Fact]
        public void GetById_returns_NotFound_when_missing()
        {
            // Act
            var actionResult = _sut.GetById(999);

            // Assert
            Assert.IsType<NotFoundResult>(actionResult.Result);
        }

        [Fact]
        public async Task Create_returns_CreatedAtAction_with_new_product()
        {
            // Arrange
            var newProduct = new Product { Name = "Novo Produto", Price = 100 };

            // Act
            var actionResult = await _sut.Create(newProduct);

            // Assert wrapper
            Assert.IsType<ActionResult<Product>>(actionResult);

            var createdAt = Assert.IsType<CreatedAtActionResult>(actionResult.Result);
            Assert.Equal(nameof(ProductController.GetById), createdAt.ActionName);

            // Route values should contain id
            Assert.True(createdAt.RouteValues?.ContainsKey("id"));
            var createdProduct = Assert.IsType<Product>(createdAt.Value);
            Assert.Equal("Novo Produto", createdProduct.Name);
            Assert.Equal(100, createdProduct.Price);
            Assert.Equal(4, createdProduct.Id); // esperado: max anterior (3) + 1
        }

        [Fact]
        public async Task Update_returns_NoContent_when_product_exists()
        {
            // Arrange
            var updated = new Product { Name = "Teclado Mecânico", Price = 300 };

            // Act
            var result = await _sut.Update(1, updated);

            // Assert
            Assert.IsType<NoContentResult>(result);

            // Confirmar alteração
            var getResult = _sut.GetById(1);
            var ok = Assert.IsType<OkObjectResult>(getResult.Result);
            var product = Assert.IsType<Product>(ok.Value);
            Assert.Equal("Teclado Mecânico", product.Name);
            Assert.Equal(300, product.Price);
        }

        [Fact]
        public async Task Update_returns_NotFound_when_product_missing()
        {
            // Arrange
            var updated = new Product { Name = "Inexistente", Price = 10 };

            // Act
            var result = await _sut.Update(999, updated);

            // Assert
            Assert.IsType<NotFoundResult>(result);
        }

        [Fact]
        public void Delete_returns_NoContent_when_product_exists()
        {
            // Act
            var result = _sut.Delete(2);

            // Assert
            Assert.IsType<NoContentResult>(result);

            // Confirmar remoção
            var getAfter = _sut.GetById(2);
            Assert.IsType<NotFoundResult>(getAfter.Result);
        }

        [Fact]
        public void Delete_returns_NotFound_when_product_missing()
        {
            // Act
            var result = _sut.Delete(999);

            // Assert
            Assert.IsType<NotFoundResult>(result);
        }
    }
}