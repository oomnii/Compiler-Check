#include <algorithm>
#include <iostream>
#include <string>

int main() {
    std::string s;
    if (!std::getline(std::cin, s)) {
        return 1;
    }
    std::reverse(s.begin(), s.end());
    std::cout << s << '\n';
    return 0;
}
