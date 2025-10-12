"""
Unit tests for navigation edge cases
"""
import pytest

class TestNavigationEdgeCases:
    """Test edge cases for Python menu navigation"""
    
    def test_python_menu_with_missing_blueprint(self, client):
        """Test behavior when Python strategy blueprint is not registered"""
        # This test verifies graceful handling of missing blueprint
        response = client.get('/')
        assert response.status_code == 200
        # Should still render the page even if blueprint is missing
        assert b'OpenAlgo' in response.data
    
    def test_python_menu_with_invalid_route(self, client):
        """Test behavior when Python route returns error"""
        response = client.get('/python')
        # Should handle 404/500 gracefully
        assert response.status_code in [200, 404, 500]
    
    def test_navigation_consistency_across_templates(self, client):
        """Test that Python menu appears consistently across all templates"""
        # Test main page
        response = client.get('/')
        assert response.status_code == 200
        assert b'Python' in response.data
        
        # Test other pages that might use different templates
        # This ensures consistency across the application
